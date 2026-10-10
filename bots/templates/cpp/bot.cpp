// Kelly game bot (C++).
// Edit ONLY the section marked below. Everything after it talks to the referee.
// Debug output goes to std::cerr, never std::cout: stdout is reserved for your bets.
// Build: python3 build.py   (the referee does this for you before the tournament)
#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>
using namespace std;

// The game state, updated every round.
struct State {
    char role = 'A';            // 'A' or 'B' (you play A in one game, B in the other)
    int round = 0;              // this round, starting at 0
    vector<double> probs;       // probs[k] = probability that A wins round k (all rounds)
    long long my_capital = 0;   // your money now
    long long opp_capital = 0;  // opponent's money now
    double time_used = 0;       // seconds spent in choose_bet so far this game (timed by your bot)
};

// ================== EDIT ONLY THIS SECTION ==================
// Write your strategy in choose_bet. You may add #includes and helper functions here.
// Return a whole number. At most 20% of my_capital (rounded down); a bigger bet is lowered to that.
// You have 120 s per game. The referee's count is slightly higher than time_used (message delays),
// so keep a margin, e.g. stop thinking hard once s.time_used > 110.

// Your chance of winning round k.
double my_chance(const State& s, int k) {
    double p = s.probs[k];
    return s.role == 'A' ? p : 1.0 - p;
}

// The most you may bet now: 20% of your money, rounded down.
long long max_bet(const State& s) {
    return s.my_capital * 20 / 100;
}

long long choose_bet(const State& s) {
    // TODO: your strategy here. For example, my_chance(s, s.round) is your chance this round
    // and max_bet(s) is the most you may bet.
    return 0;
}

// ============================================================
// Do not edit below this line.

// Minimal readers for the referee's flat JSON messages ("key":value, no spaces).
static size_t at(const string& s, const string& key) {
    size_t p = s.find("\"" + key + "\":");
    return p == string::npos ? p : p + key.size() + 3;
}
static double num(const string& s, const string& key) {
    size_t p = at(s, key);
    return p == string::npos ? 0 : strtod(s.c_str() + p, nullptr);
}
static string str(const string& s, const string& key) {
    size_t p = at(s, key);
    string out;
    if (p == string::npos || s[p] != '"') return out;
    for (size_t i = p + 1; i < s.size() && s[i] != '"'; ++i) {
        if (s[i] == '\\' && i + 1 < s.size()) ++i;
        out += s[i];
    }
    return out;
}
static vector<double> arr(const string& s, const string& key) {
    vector<double> out;
    size_t p = at(s, key);
    if (p == string::npos || s[p] != '[') return out;
    const char* c = s.c_str() + p + 1;
    while (*c && *c != ']') {
        char* end;
        out.push_back(strtod(c, &end));
        c = end;
        while (*c == ',' || *c == ' ') ++c;
    }
    return out;
}

int main() {
    ios::sync_with_stdio(false);
    State st;
    string line;
    while (getline(cin, line)) {
        string type = str(line, "type");
        if (type == "start") {
            st = State();
            st.role = str(line, "role")[0];
            st.probs = arr(line, "probs");
            st.my_capital = (long long)num(line, "my_capital");
            st.opp_capital = (long long)num(line, "opp_capital");
            cout << "{\"ready\":true}" << endl;              // endl flushes
        } else if (type == "bet") {
            st.round = (int)num(line, "round");
            st.my_capital = (long long)num(line, "my_capital");
            st.opp_capital = (long long)num(line, "opp_capital");
            auto started = chrono::steady_clock::now();
            long long bet = choose_bet(st);
            st.time_used += chrono::duration<double>(chrono::steady_clock::now() - started).count();
            cout << "{\"bet\":" << bet << "}" << endl;
        }
    }
}
