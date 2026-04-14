#include <iostream>
#include <fstream>
#include <sstream>
#include <vector>
#include <cmath>
#include <algorithm>
#include <cstring>
#include <ctime>
#include <numeric>
#include <map>
#include <limits>
#include <stdexcept>
#include <iomanip>   // NEW: for setprecision

#include "conversions.h"
#include "ins_mechanization.h"
#include "loosely_coupled_algorithm.h"

INS_MECHANIZATION ins_mech;

const float D2R = 3.14159265358979323846f / 180.0f;
const float R2D = 180.0f / 3.14159265358979323846f;

// ------------------------------------------------------------------------
// Data structures
// ------------------------------------------------------------------------
struct IMUData {
    double time;
    float ax, ay, az;
    float wx, wy, wz;
};

struct GNSSData {
    double time;
    double lat;  // degrees
    double lon;  // degrees
    float h;     // meters
    float vn, ve;
};

struct OutageInterval {
    double start;
    double end;
};

// ------------------------------------------------------------------------
// Dataset configuration
// ------------------------------------------------------------------------
struct DatasetConfig {
    std::string dataset_name;
    std::string imu_file;
    std::string gnss_file;

    int imu_start_idx  = 821;
    int gnss_start_idx = 8;

    int imu_rate  = 200;
    int gnss_rate = 1;

    int gnss_col_time = 0;
    int gnss_col_lat  = 1;
    int gnss_col_lon  = 2;
    int gnss_col_h    = 3;
    int gnss_col_vn   = 4;
    int gnss_col_ve   = 5;

    float yaw_override;  // NaN = auto

    float lever_arm[3];

    std::vector<OutageInterval> outages;

    DatasetConfig() : yaw_override(std::numeric_limits<float>::quiet_NaN()) {
        lever_arm[0] = 0.0f; lever_arm[1] = 0.0f; lever_arm[2] = -1.0f;
    }

    double matchWindow() const {
        return 0.0035;
    }
};

// ------------------------------------------------------------------------
// Helper functions (unchanged)
// ------------------------------------------------------------------------
static std::string trim(const std::string& s) {
    size_t start = s.find_first_not_of(" \t\r\n");
    size_t end   = s.find_last_not_of(" \t\r\n");
    if (start == std::string::npos) return "";
    return s.substr(start, end - start + 1);
}

DatasetConfig loadConfig(const std::string& filename) {
    std::ifstream file(filename);
    if (!file.is_open())
        throw std::runtime_error("Cannot open config file: " + filename);

    std::map<std::string, std::string> kv;
    std::vector<std::pair<std::string, std::string>> outage_lines;

    std::string line;
    while (std::getline(file, line)) {
        line = trim(line);
        if (line.empty() || line[0] == '#') continue;

        size_t eq = line.find('=');
        if (eq == std::string::npos) continue;

        std::string key = trim(line.substr(0, eq));
        std::string val = trim(line.substr(eq + 1));

        if (key.size() > 7 && key.substr(0, 7) == "outage_"
                && key != "outage_intervals_count") {
            outage_lines.push_back(std::make_pair(key, val));
        } else {
            kv[key] = val;
        }
    }

    DatasetConfig cfg;

    auto get = [&](const std::string& k, const std::string& def = "") -> std::string {
        auto it = kv.find(k);
        return (it != kv.end()) ? it->second : def;
    };

    cfg.dataset_name = get("dataset_name", "Unknown");
    cfg.imu_file     = get("imu_file");
    cfg.gnss_file    = get("gnss_file");

    if (!get("imu_start_idx").empty())  cfg.imu_start_idx  = std::stoi(get("imu_start_idx"));
    if (!get("gnss_start_idx").empty()) cfg.gnss_start_idx = std::stoi(get("gnss_start_idx"));
    if (!get("imu_rate").empty())       cfg.imu_rate       = std::stoi(get("imu_rate"));
    if (!get("gnss_rate").empty())      cfg.gnss_rate      = std::stoi(get("gnss_rate"));

    if (!get("gnss_col_time").empty()) cfg.gnss_col_time = std::stoi(get("gnss_col_time"));
    if (!get("gnss_col_lat").empty())  cfg.gnss_col_lat  = std::stoi(get("gnss_col_lat"));
    if (!get("gnss_col_lon").empty())  cfg.gnss_col_lon  = std::stoi(get("gnss_col_lon"));
    if (!get("gnss_col_h").empty())    cfg.gnss_col_h    = std::stoi(get("gnss_col_h"));
    if (!get("gnss_col_vn").empty())   cfg.gnss_col_vn   = std::stoi(get("gnss_col_vn"));
    if (!get("gnss_col_ve").empty())   cfg.gnss_col_ve   = std::stoi(get("gnss_col_ve"));

    std::string yaw_str = get("yaw_override", "auto");
    if (yaw_str == "auto") {
        cfg.yaw_override = std::numeric_limits<float>::quiet_NaN();
    } else {
        cfg.yaw_override = std::stof(yaw_str);
    }

    std::string la_str = get("lever_arm", "");
    if (!la_str.empty()) {
        std::istringstream la_ss(la_str);
        std::string tok;
        int la_idx = 0;
        while (std::getline(la_ss, tok, ',') && la_idx < 3) {
            cfg.lever_arm[la_idx++] = std::stof(trim(tok));
        }
        if (la_idx != 3)
            std::cerr << "Warning: lever_arm needs 3 values (x,y,z). Got " << la_idx << ".\n";
    }

    for (const auto& ol : outage_lines) {
        const std::string& val = ol.second;
        size_t comma = val.find(',');
        if (comma == std::string::npos) continue;
        try {
            OutageInterval oi;
            oi.start = std::stod(trim(val.substr(0, comma)));
            oi.end   = std::stod(trim(val.substr(comma + 1)));
            cfg.outages.push_back(oi);
        } catch (...) {
            std::cerr << "Warning: could not parse outage line: "
                      << ol.first << " = " << val << "\n";
        }
    }

    return cfg;
}

std::vector<std::vector<std::string>> readCSV(const std::string& filename) {
    std::vector<std::vector<std::string>> data;
    std::ifstream file(filename);
    if (!file.is_open()) {
        std::cerr << "Error: cannot open file: " << filename << "\n";
        return data;
    }
    std::string line;
    while (std::getline(file, line)) {
        if (line.empty()) continue;
        std::vector<std::string> row;
        std::stringstream ss(line);
        std::string cell;
        while (std::getline(ss, cell, ',')) row.push_back(cell);

        if (row.size() == 1) {
            row.clear();
            std::istringstream ws(line);
            std::string token;
            while (ws >> token) row.push_back(token);
        }
        if (!row.empty()) data.push_back(row);
    }
    return data;
}

std::vector<IMUData> loadIMU(const std::string& filename, int start_idx_1based) {
    auto raw = readCSV(filename);
    std::vector<IMUData> imu;
    int start = start_idx_1based - 1;
    for (size_t i = 0; i < raw.size(); ++i) {
        if ((int)i < start) continue;
        const auto& row = raw[i];
        if (row.size() < 7) continue;
        try {
            IMUData d;
            d.time = std::stod(row[0]);
            d.ax   = std::stof(row[1]);
            d.ay   = std::stof(row[2]);
            d.az   = std::stof(row[3]);
            d.wx   = std::stof(row[4]) * D2R;
            d.wy   = std::stof(row[5]) * D2R;
            d.wz   = std::stof(row[6]) * D2R;
            imu.push_back(d);
        } catch (const std::exception& e) {
            std::cerr << "Skipping IMU line " << i+1 << ": " << e.what() << "\n";
        }
    }
    return imu;
}

std::vector<GNSSData> loadGNSS(const std::string& filename, int start_idx_1based, const DatasetConfig& cfg) {
    auto raw = readCSV(filename);
    std::vector<GNSSData> gnss;
    int start = start_idx_1based - 1;

    int max_col = std::max({cfg.gnss_col_time, cfg.gnss_col_lat, cfg.gnss_col_lon,
                            cfg.gnss_col_h, cfg.gnss_col_vn, cfg.gnss_col_ve});

    for (size_t i = 0; i < raw.size(); ++i) {
        if ((int)i < start) continue;
        const auto& row = raw[i];
        if ((int)row.size() <= max_col) continue;
        try {
            GNSSData d;
            d.time = std::stod(row[cfg.gnss_col_time]);
            d.lat  = std::stod(row[cfg.gnss_col_lat]);
            d.lon  = std::stod(row[cfg.gnss_col_lon]);
            d.h    = std::stof(row[cfg.gnss_col_h]);
            d.vn   = std::stof(row[cfg.gnss_col_vn]);
            d.ve   = std::stof(row[cfg.gnss_col_ve]);
            gnss.push_back(d);
        } catch (const std::exception& e) {
            std::cerr << "Skipping GNSS line " << i+1 << ": " << e.what() << "\n";
        }
    }
    return gnss;
}

void initAttitudeFromIMU(const std::vector<IMUData>& imu, int nSamples,
                         float& roll, float& pitch, float& yaw,
                         float biases[6]) {
    if ((int)imu.size() < nSamples) {
        std::cerr << "Warning: only " << imu.size() << " IMU samples for init (need "
                  << nSamples << "). Using all available.\n";
        nSamples = (int)imu.size();
    }
    float ax_avg=0, ay_avg=0, az_avg=0, wx_avg=0, wy_avg=0, wz_avg=0;
    for (int i = 0; i < nSamples; ++i) {
        ax_avg += imu[i].ax; ay_avg += imu[i].ay; az_avg += imu[i].az;
        wx_avg += imu[i].wx; wy_avg += imu[i].wy; wz_avg += imu[i].wz;
    }
    ax_avg /= nSamples; ay_avg /= nSamples; az_avg /= nSamples;
    wx_avg /= nSamples; wy_avg /= nSamples; wz_avg /= nSamples;

    float norm = std::sqrt(ax_avg*ax_avg + ay_avg*ay_avg + az_avg*az_avg);
    ax_avg /= norm; ay_avg /= norm; az_avg /= norm;

    pitch = std::atan(ax_avg / std::sqrt(ay_avg*ay_avg + az_avg*az_avg));
    roll  = std::atan2(-ay_avg, -az_avg);

    float sin_psi = -wy_avg * std::cos(roll) + wz_avg * std::sin(roll);
    float cos_psi =  wx_avg * std::cos(pitch)
                  +  wy_avg * std::sin(roll) * std::sin(pitch)
                  +  wz_avg * std::cos(roll) * std::sin(pitch);
    yaw = std::atan2(sin_psi, cos_psi);

    std::memset(biases, 0, 6 * sizeof(float));
}

bool isInOutage(double time, const std::vector<OutageInterval>& outages) {
    for (const auto& o : outages)
        if (time >= o.start && time <= o.end) return true;
    return false;
}

double rms(const std::vector<double>& v) {
    if (v.empty()) return 0.0;
    double sum_sq = 0.0;
    for (double x : v) sum_sq += x * x;
    return std::sqrt(sum_sq / v.size());
}

// ------------------------------------------------------------------------
// Main
// ------------------------------------------------------------------------
int main(int argc, char* argv[]) {
    if (argc < 2) {
        std::cerr << "Usage: " << argv[0] << " <config_file.txt>\n";
        return 1;
    }

    DatasetConfig cfg;
    try {
        cfg = loadConfig(argv[1]);
    } catch (const std::exception& e) {
        std::cerr << "Error loading config: " << e.what() << "\n";
        return 1;
    }

    // ===== SET GLOBAL OUTPUT PRECISION TO 10 DECIMAL PLACES =====
    std::cout << std::fixed << std::setprecision(10);

    std::cout << ">>> Running with dataset: " << cfg.dataset_name << "\n";

    // Determine output directory (same as config file)
    std::string config_path = argv[1];
    size_t last_slash = config_path.find_last_of("/\\");
    std::string out_dir = (last_slash == std::string::npos) ? "." : config_path.substr(0, last_slash);
    std::cout << "Output directory: " << out_dir << "\n";

    // Load data
    std::vector<IMUData> imu  = loadIMU(cfg.imu_file, cfg.imu_start_idx);
    std::vector<GNSSData> gnss = loadGNSS(cfg.gnss_file, cfg.gnss_start_idx, cfg);

    std::cout << "Loaded " << imu.size() << " IMU samples, "
              << gnss.size() << " GNSS samples.\n";

    if (imu.empty() || gnss.empty()) {
        std::cerr << "Error: could not load data files.\n";
        return 1;
    }

    // Prepare clean GNSS reference (without outages)
    std::vector<GNSSData> gnss_ref_valid;
    for (const auto& g : gnss) {
        if (!isInOutage(g.time, cfg.outages)) {
            gnss_ref_valid.push_back(g);
        }
    }
    std::cout << "  GNSS reference points (outages removed): " << gnss_ref_valid.size() << "\n";

    // Time matching window
    double match_window = cfg.matchWindow();
    std::cout << "IMU rate: " << cfg.imu_rate << " Hz  |  GNSS rate: "
              << cfg.gnss_rate << " Hz  |  match window: "
              << match_window << " s\n";

    // Kalman filter configuration (unchanged)
    LOOSELY_COUPLED_ALGORITHM::Config kf_config;
    kf_config.init_att_unc   = 1.0f * D2R;
    kf_config.init_vel_unc   = 0.1f;
    kf_config.init_pos_unc   = 10.0f;
    kf_config.init_b_a_unc   = 20.0f * 9.80665e-6f;
    kf_config.init_b_g_unc   = 0.1f * D2R / 3600.0f;
    kf_config.gyro_noise_PSD  = std::pow(0.02f * D2R / 60.0f, 2);
    kf_config.accel_noise_PSD = std::pow(200.0f * 9.80665e-6f, 2);
    kf_config.accel_bias_PSD  = 1.0e-7f;
    kf_config.gyro_bias_PSD   = 2.0e-12f;
    kf_config.pos_meas_SD     = 1.5f;
    kf_config.vel_meas_SD     = 0.1f;

    LOOSELY_COUPLED_ALGORITHM kf(kf_config, cfg.lever_arm);
    std::cout << "Lever arm (body): [" << cfg.lever_arm[0] << ", "
              << cfg.lever_arm[1] << ", " << cfg.lever_arm[2] << "] m\n";

    // Initialise attitude from first IMU samples
    float roll, pitch, yaw;
    float biases[6];
    initAttitudeFromIMU(imu, 6000, roll, pitch, yaw, biases);
    if (!std::isnan(cfg.yaw_override)) {
        yaw = cfg.yaw_override * D2R;
        std::cout << "Yaw overridden to " << cfg.yaw_override << " deg\n";
    }

    CONVERSIONS conv;

    // Initial position/velocity from first GNSS
    double L_b      = gnss[0].lat * D2R;
    double lambda_b = gnss[0].lon * D2R;
    double h_b      = gnss[0].h;
    float v_eb_n[3] = {gnss[0].vn, gnss[0].ve, 0.0f};
    float C_b_n[3][3];
    conv.Euler2DCM(C_b_n, roll, pitch, yaw);

    double r_eb_e[3];
    float v_eb_e[3];
    float C_b_e[3][3];
    conv.NED2ECEF(r_eb_e, v_eb_e, C_b_e, L_b, lambda_b, h_b, v_eb_n, C_b_n);
    conv.ECEF2NED(L_b, lambda_b, h_b, v_eb_n, C_b_n, r_eb_e, v_eb_e, C_b_e);
    conv.DCM2Euler(roll, pitch, yaw, C_b_e);

    kf.initializeP();

    // ===== ADDED: structure to store full trajectory at regular intervals =====
    struct FullTrajPoint {
        double time;
        double lat;
        double lon;
        double alt;
        float vn;
        float ve;
    };
    std::vector<FullTrajPoint> full_traj;

    const double RECORD_INTERVAL = 1.0 / 200.0;   // seconds (1 Hz)
    double last_record_time = -1e9;       // force first recording
    // ========================================================================

    // Prepare storage for output
    struct StateAtGNSS {
        double time;
        double lat_deg, lon_deg, h_m;
        double vn_mps, ve_mps;
        double acc_bias[3], gyro_bias[3];
    };
    std::vector<StateAtGNSS> state_history;   // kept for backward compatibility (if needed)

    // Main processing loop
    double last_time = imu[0].time;
    int imu_idx = 0;
    int gnss_idx = 0;

    std::vector<double> err_times, horz_errors, vert_errors, vn_errors, ve_errors;

    for (; imu_idx < (int)imu.size(); ++imu_idx) {
        const IMUData& s = imu[imu_idx];
        double current_time = s.time;
        float dt = (float)(current_time - last_time);
        if (dt <= 0.0f) { last_time = current_time; continue; }
        last_time = current_time;

        float f_ib_b[3] = {s.ax - biases[0], s.ay - biases[1], s.az - biases[2]};
        float omega_ib_b[3] = {s.wx - biases[3], s.wy - biases[4], s.wz - biases[5]};

        double new_r_eb_e[3];
        float new_v_eb_e[3];
        float new_C_b_e[3][3];
        ins_mech.ECEF_Nav_Eq(new_r_eb_e, new_v_eb_e, new_C_b_e,
                             dt, r_eb_e, v_eb_e, C_b_e, f_ib_b, omega_ib_b);

        std::memcpy(r_eb_e, new_r_eb_e, 3 * sizeof(double));
        std::memcpy(v_eb_e, new_v_eb_e, 3 * sizeof(float));
        std::memcpy(C_b_e,  new_C_b_e,  9 * sizeof(float));

        double L_b_rad, lambda_b_rad, h_b_m;
        float v_eb_n_dummy[3], C_b_n_dummy[3][3];
        conv.ECEF2NED(L_b_rad, lambda_b_rad, h_b_m,
                      v_eb_n_dummy, C_b_n_dummy, r_eb_e, v_eb_e, C_b_e);
        kf.propagate_P_matrix(dt, f_ib_b, C_b_e, r_eb_e, L_b_rad);

        // GNSS matching
        while (gnss_idx < (int)gnss.size() &&
               gnss[gnss_idx].time < current_time - match_window) {
            ++gnss_idx;
        }

        while (gnss_idx < (int)gnss.size() &&
               std::abs(gnss[gnss_idx].time - current_time) <= match_window) {

            double gnss_time = gnss[gnss_idx].time;

            double gnss_r_eb_e[3];
            float gnss_v_eb_e[3];
            conv.pv_NED2ECEF(gnss[gnss_idx].lat * D2R,
                             gnss[gnss_idx].lon * D2R,
                             gnss[gnss_idx].h,
                             gnss[gnss_idx].vn, gnss[gnss_idx].ve, 0.0f,
                             gnss_r_eb_e, gnss_v_eb_e);

            if (!isInOutage(gnss_time, cfg.outages)) {
                kf.measurement_update(gnss_r_eb_e, gnss_v_eb_e,
                                      omega_ib_b, r_eb_e, v_eb_e, C_b_e, biases);
            }

            // Convert current INS state to NED for logging
            double lat_deg, lon_deg, h_m;
            float vn_mps, ve_mps, vd_dummy;
            conv.ECEF2NED(L_b_rad, lambda_b_rad, h_b_m,
                          v_eb_n_dummy, C_b_n_dummy, r_eb_e, v_eb_e, C_b_e);
            lat_deg = L_b_rad * R2D;
            lon_deg = lambda_b_rad * R2D;
            h_m = h_b_m;
            vn_mps = v_eb_n_dummy[0];
            ve_mps = v_eb_n_dummy[1];

            // Record state at this GNSS epoch (kept for potential bias logging)
            StateAtGNSS rec;
            rec.time = gnss_time;
            rec.lat_deg = lat_deg;
            rec.lon_deg = lon_deg;
            rec.h_m = h_m;
            rec.vn_mps = vn_mps;
            rec.ve_mps = ve_mps;
            std::memcpy(rec.acc_bias, biases, 3*sizeof(double));
            std::memcpy(rec.gyro_bias, biases+3, 3*sizeof(double));
            state_history.push_back(rec);

            // Compute error (as before)
            double ref_lat = gnss[gnss_idx].lat;
            double ref_lon = gnss[gnss_idx].lon;
            double ref_h   = gnss[gnss_idx].h;
            float ref_vn   = gnss[gnss_idx].vn;
            float ref_ve   = gnss[gnss_idx].ve;
            const double R_earth = 6371000.0;
            double dlat = (lat_deg - ref_lat) * D2R;
            double dlon = (lon_deg - ref_lon) * D2R;
            double a = std::sin(dlat/2)*std::sin(dlat/2) +
                       std::cos(ref_lat*D2R)*std::cos(lat_deg*D2R)*
                       std::sin(dlon/2)*std::sin(dlon/2);
            double horz_error = R_earth * 2.0 * std::atan2(std::sqrt(a), std::sqrt(1.0-a));
            double vert_error = std::abs(h_m - ref_h);
            double vn_error = vn_mps - ref_vn;
            double ve_error = ve_mps - ref_ve;

            err_times.push_back(gnss_time);
            horz_errors.push_back(horz_error);
            vert_errors.push_back(vert_error);
            vn_errors.push_back(vn_error);
            ve_errors.push_back(ve_error);

            ++gnss_idx;
        }

        // ===== ADDED: record the current INS state at a fixed interval =====
        // Compute current NED state (already computed above in L_b_rad, etc.)
        double lat_deg = L_b_rad * R2D;
        double lon_deg = lambda_b_rad * R2D;
        double alt_m   = h_b_m;
        float vn_mps   = v_eb_n_dummy[0];
        float ve_mps   = v_eb_n_dummy[1];

        if (current_time - last_record_time >= RECORD_INTERVAL) {
            full_traj.push_back({current_time, lat_deg, lon_deg, alt_m, vn_mps, ve_mps});
            last_record_time = current_time;
        }
        // ====================================================================
    }

    std::cout << "Total GNSS epochs matched: " << err_times.size() << "\n";
    std::cout << "Total trajectory points recorded: " << full_traj.size() << "\n";

    // ------------------------------------------------------------------------
    // Write output files
    // ------------------------------------------------------------------------
    // 1. Errors CSV (unchanged)
    std::cout << "BEGIN_ERRORS\n";
    std::cout << "time,horz_error_m,vert_error_m,vn_error_mps,ve_error_mps\n";
    for (size_t i = 0; i < err_times.size(); ++i) {
        std::cout << err_times[i] << ","
                  << horz_errors[i] << ","
                  << vert_errors[i] << ","
                  << vn_errors[i] << ","
                  << ve_errors[i] << "\n";
    }
    std::cout << "END_ERRORS\n";

    // 2. Trajectory file (continuous, from full_traj)
    std::cout << "BEGIN_TRAJ\n";
    std::cout << "GPStime,lat_deg,lon_deg,alt_m,vn_mps,ve_mps\n";
    for (const auto& p : full_traj) {
        std::cout << p.time << ","
                  << p.lat << ","
                  << p.lon << ","
                  << p.alt << ","
                  << p.vn << ","
                  << p.ve << "\n";
    }
    std::cout << "END_TRAJ\n";

    // 3. GNSS reference (outages removed)
    // Note: altitude column renamed to alt_m for GUI consistency
    std::cout << "BEGIN_GNSS_REF\n";
    std::cout << "GPStime,lat_deg,lon_deg,alt_m,vn_mps,ve_mps\n";
    for (const auto& g : gnss_ref_valid) {
        std::cout << g.time << ","
                  << g.lat << ","
                  << g.lon << ","
                  << g.h << ","
                  << g.vn << ","
                  << g.ve << "\n";
    }
    std::cout << "END_GNSS_REF\n";

    // 4. Biases file (optional, omitted for brevity)

    return 0;
}