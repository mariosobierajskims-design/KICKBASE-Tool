# Kickbase v4 API paths. Confirmed live against api.kickbase.com on 2026-09-05
# (see raw_samples/ produced by kickbase_tool/dump_raw.py) rather than taken
# on faith from the public (unofficial, community-maintained) documentation
# at github.com/kevinskyba/kickbase-api-doc, which lists the paths correctly
# but ships almost no example response bodies.
#
# Important, confirmed live: COMPETITION_PLAYERS does NOT return the full
# Bundesliga player pool -- it returns only the ~2 teams involved in the
# current matchday's context. The full pool has to be assembled by calling
# COMPETITION_TEAM_PROFILE once per team (18 teams) to get each team's
# roster of player ids, then COMPETITION_PLAYER_DETAIL per player.

LOGIN = "/v4/user/login"

LEAGUE_SQUAD = "/v4/leagues/{league_id}/squad"
LEAGUE_MARKET = "/v4/leagues/{league_id}/market"
LEAGUE_ME = "/v4/leagues/{league_id}/me"
LEAGUE_RANKING = "/v4/leagues/{league_id}/ranking"
LEAGUE_PLAYER_PERFORMANCE = "/v4/leagues/{league_id}/players/{player_id}/performance"

COMPETITION_PLAYERS = "/v4/competitions/{competition_id}/players"
COMPETITION_PLAYER_DETAIL = "/v4/competitions/{competition_id}/players/{player_id}"
COMPETITION_PLAYER_PERFORMANCE = "/v4/competitions/{competition_id}/players/{player_id}/performance"
COMPETITION_TABLE = "/v4/competitions/{competition_id}/table"
COMPETITION_MATCHDAYS = "/v4/competitions/{competition_id}/matchdays"
COMPETITION_TEAM_PROFILE = "/v4/competitions/{competition_id}/teams/{team_id}/teamprofile"
