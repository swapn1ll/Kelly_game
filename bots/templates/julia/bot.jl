# Kelly game bot (Julia).
# Edit ONLY the section marked below. Everything after it talks to the referee.
# Debug output goes to stderr, never stdout: stdout is reserved for your bets.

# The game state, updated every round.
mutable struct State
    role::String                # "A" or "B" (you play A in one game, B in the other)
    rounds::Int                 # rounds in this game
    round::Int                  # this round, starting at 0
    probs::Vector{Float64}      # probs[k + 1] = probability that A wins round k (all rounds)
    my_capital::Int             # your money now
    opp_capital::Int            # opponent's money now
    time_used::Float64          # seconds spent in choose_bet so far this game (timed by your bot)
end

# ================== EDIT ONLY THIS SECTION ==================
# Write your strategy in choose_bet. You may add helper functions here.
# s.round starts at 0 but Julia arrays start at 1, so this round's probability is s.probs[s.round + 1].
# Return a whole number. At most 20% of your money (rounded down); a bigger bet is lowered to that.
# You have 120 s per game. The referee's count is slightly higher than s.time_used (message delays),
# so keep a margin, e.g. stop thinking hard once s.time_used > 110.

# Your chance of winning round k (k starts at 0, like s.round).
function my_chance(s, k = s.round)
    p = s.probs[k + 1]
    return s.role == "A" ? p : 1 - p
end

# The most you may bet now: 20% of your money, rounded down.
max_bet(s) = div(s.my_capital * 20, 100)

function choose_bet(s)
    # TODO: your strategy here. For example, my_chance(s) is your chance this round
    # and max_bet(s) is the most you may bet.
    return 0
end

# ============================================================
# Do not edit below this line.

# Minimal readers for the referee's flat JSON messages ("key":value, no spaces).
function keypos(s, key)
    r = findfirst("\"" * key * "\":", s)
    return r === nothing ? nothing : last(r) + 1
end

function num(s, key)
    p = keypos(s, key)
    p === nothing && return 0.0
    e = p
    while e <= lastindex(s) && (isdigit(s[e]) || s[e] in ('-', '+', '.', 'e', 'E'))
        e += 1
    end
    return parse(Float64, SubString(s, p, e - 1))
end

function str(s, key)
    p = keypos(s, key)
    (p === nothing || s[p] != '"') && return ""
    out = IOBuffer()
    i = p + 1
    while i <= lastindex(s) && s[i] != '"'
        if s[i] == '\\'
            i += 1
        end
        write(out, s[i])
        i = nextind(s, i)
    end
    return String(take!(out))
end

function arr(s, key)
    p = keypos(s, key)
    (p === nothing || s[p] != '[') && return Float64[]
    q = findnext(']', s, p)
    inner = strip(SubString(s, p + 1, q - 1))
    isempty(inner) && return Float64[]
    return [parse(Float64, strip(x)) for x in split(inner, ',')]
end

int(s, key) = round(Int, num(s, key))

function main()
    st = nothing
    for line in eachline(stdin)
        t = str(line, "type")
        if t == "start"
            st = State(str(line, "role"), int(line, "rounds"), 0, arr(line, "probs"),
                       int(line, "my_capital"), int(line, "opp_capital"), 0.0)
            println("{\"ready\":true}")
            flush(stdout)
        elseif t == "bet"
            st.round = int(line, "round")
            st.my_capital = int(line, "my_capital")
            st.opp_capital = int(line, "opp_capital")
            started = time()
            bet = Int(choose_bet(st))
            st.time_used += time() - started
            println("{\"bet\":", bet, "}")
            flush(stdout)
        end
    end
end

main()
