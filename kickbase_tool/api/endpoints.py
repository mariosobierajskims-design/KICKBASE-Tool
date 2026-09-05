# Kickbase v4 API paths, taken from the public (unofficial, community-maintained)
# documentation at github.com/kevinskyba/kickbase-api-doc. The doc lists these paths
# with confidence, but ships almost no example response bodies for GET requests and
# none for POST/PUT/DELETE, so the *shape* of each response is inferred defensively
# in kickbase_tool.data.normalize rather than hard-coded here.

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
