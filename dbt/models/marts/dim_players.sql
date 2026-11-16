-- One row per player: who they are, from their most recent season snapshot.
--
-- Type 1 dimension (latest values overwrite older ones). That's right for things that
-- don't change (name, birth date, bats, throws) and good enough for labels. For anything
-- that does change and matters to a model (weight, listed position), join
-- stg_mlb__players on (player_id, season) instead.
--
-- Age isn't stored: it depends on the date. Compute it from birth_date at the game date.

with player_seasons as (

    select * from {{ ref('stg_mlb__players') }}

),

latest as (

    select *
    from player_seasons
    qualify row_number() over (partition by player_id order by season desc) = 1

),

seasons as (

    select
        player_id,
        min(season)     as first_season_loaded,
        max(season)     as last_season_loaded,
        count(*)        as seasons_loaded
    from player_seasons
    group by player_id

)

select
    l.player_id,
    l.full_name,
    l.first_name,
    l.last_name,
    l.use_first_name,
    l.boxscore_name,
    l.birth_date,
    l.birth_country,
    l.mlb_debut_date,
    l.draft_year,
    l.bats,
    l.throws,
    l.primary_position,
    l.position_type,
    l.height_in,
    l.weight_lb,
    s.first_season_loaded,
    s.last_season_loaded,
    s.seasons_loaded
from latest l
join seasons s using (player_id)
