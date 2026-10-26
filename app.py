import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timezone

st.set_page_config(
    page_title="20/21",
    page_icon="⚽",
    layout="wide"
)

BASE_URL = (
    "https://raw.githubusercontent.com/"
    "oladeeayo/open-matchday/master/data/"
)

LEAGUES = {
    "Premier League": "ENG_1_premier-league",
    "La Liga": "ESP_1_la-liga",
    "Serie A": "ITA_1_serie-a",
    "Bundesliga": "GER_1_bundesliga",
    "Ligue 1": "FRA_1_ligue-1",
    "Eredivisie": "NED_1_eredivisie",
    "Primeira Liga": "POR_1_primeira-liga",
}

SEASONS = {
    "2026/27": "2627",
    "2025/26": "2526",
    "2024/25": "2425",
    "2023/24": "2324",
}


@st.cache_data(ttl=3600)
def load_csv(url):
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    from io import StringIO
    return pd.read_csv(StringIO(response.text))


def get_column(df, possible_names):
    lookup = {str(c).lower(): c for c in df.columns}
    for name in possible_names:
        if name.lower() in lookup:
            return lookup[name.lower()]
    return None


def normalize(df):
    columns = {
        "home": ["home", "home_team", "hometeam"],
        "away": ["away", "away_team", "awayteam"],
        "date": ["date", "datetime", "match_date"],
        "ht_home": ["ht_home", "ht_home_goals", "halftime_home"],
        "ht_away": ["ht_away", "ht_away_goals", "halftime_away"],
        "ft_home": ["ft_home", "ft_home_goals", "home_score"],
        "ft_away": ["ft_away", "ft_away_goals", "away_score"],
    }

    result = pd.DataFrame(index=df.index)
    for key, names in columns.items():
        col = get_column(df, names)
        result[key] = df[col] if col else pd.NA

    for col in ["ht_home", "ht_away", "ft_home", "ft_away"]:
        result[col] = pd.to_numeric(result[col], errors="coerce")

    return result


def assign_code(row):
    values = [
        row["ht_home"],
        row["ht_away"],
        row["ft_home"],
        row["ft_away"],
    ]
    if any(pd.isna(x) for x in values):
        return None

    first_half = row["ht_home"] + row["ht_away"]
    second_half = (
        row["ft_home"] + row["ft_away"] - first_half
    )

    if second_half < 0:
        return None
    if second_half > first_half:
        return "21"
    if first_half > second_half:
        return "20"
    return "24"


def get_url(league, season, kind):
    return f"{BASE_URL}{league}/{kind}_{season}.csv"


def fetch_history(league, season_codes):
    frames = []
    errors = []

    for season in season_codes:
        try:
            raw = load_csv(get_url(league, season, "results"))
            data = normalize(raw)
            data["season"] = season
            frames.append(data)
        except Exception as exc:
            errors.append(f"{season}: {exc}")

    if not frames:
        raise ValueError(
            "Aucun historique récupéré. Vérifie la connexion "
            "ou choisis une autre saison."
        )

    history = pd.concat(frames, ignore_index=True)
    history["code"] = history.apply(assign_code, axis=1)
    history = history.dropna(subset=["code"])
    return history, errors


def smoothed_probabilities(codes, prior, strength=8):
    counts = codes.value_counts()
    keys = ["20", "21", "24"]
    total = len(codes)
    denominator = total + strength

    return {
        key: (
            counts.get(key, 0) + strength * prior[key]
        ) / denominator
        for key in keys
    }


def estimate_match(home, away, history, global_probs):
    team_probs = {}

    for team in [home, away]:
        team_matches = history[
            (history["home"] == team)
            | (history["away"] == team)
        ].tail(20)

        team_probs[team] = smoothed_probabilities(
            team_matches["code"],
            global_probs,
            strength=8,
        )

    probabilities = {}
    for code in ["20", "21", "24"]:
        probabilities[code] = (
            0.50 * global_probs[code]
            + 0.25 * team_probs[home][code]
            + 0.25 * team_probs[away][code]
        )

    total = sum(probabilities.values())
    return {
        code: value / total
        for code, value in probabilities.items()
    }


st.title("⚽ 20/21 Analytics")
st.caption(
    "Analyse des scores à la mi-temps et en fin de match"
)

st.info(
    "Code 20 : plus de buts en première période. "
    "Code 21 : plus de buts en seconde période. "
    "Code 24 : autant de buts dans les deux périodes."
)

with st.sidebar:
    st.header("Paramètres")
    league_name = st.selectbox(
        "Championnat", list(LEAGUES.keys())
    )
    season_name = st.selectbox(
        "Saison de référence", list(SEASONS.keys())
    )
    history_count = st.selectbox(
        "Nombre de saisons historiques", [1, 2, 3]
    )
    st.caption(
        "Les probabilités sont des estimations statistiques, "
        "pas des garanties de résultat."
    )

if st.button("🔎 Analyser les matchs", type="primary"):
    league = LEAGUES[league_name]
    season_list = list(SEASONS.values())
    selected_index = season_list.index(SEASONS[season_name])
    selected_seasons = season_list[
        selected_index:selected_index + history_count
    ]

    try:
        with st.spinner("Analyse des données en cours..."):
            history, errors = fetch_history(
                league, selected_seasons
            )

            if history.empty:
                st.error(
                    "Aucun match avec scores complets "
                    "à la mi-temps et à la fin."
                )
                st.stop()

            global_counts = (
                history["code"].value_counts().to_dict()
            )
            global_total = len(history)

            global_probs = {
                code: global_counts.get(code, 0) / global_total
                for code in ["20", "21", "24"]
            }

            st.subheader("📊 Résultats historiques")
            st.write(
                f"Matchs exploitables : **{global_total}**"
            )

            cols = st.columns(3)
            for col, code in zip(cols, ["20", "21", "24"]):
                col.metric(
                    f"Code {code}",
                    f"{global_probs[code] * 100:.1f}%",
                    f"{global_counts.get(code, 0)} matchs",
                )

            st.subheader("📅 Prochains matchs")
            fixtures_url = get_url(
                league, SEASONS[season_name], "fixtures"
            )

            try:
                raw_fixtures = load_csv(fixtures_url)
                fixtures = normalize(raw_fixtures)

                fixtures = fixtures.dropna(
                    subset=["home", "away"]
                )

                fixtures["parsed_date"] = pd.to_datetime(
                    fixtures["date"], errors="coerce", utc=True
                )

                now = pd.Timestamp.now(tz="UTC")
                upcoming = fixtures[
                    fixtures["parsed_date"].isna()
                    | (fixtures["parsed_date"] >= now)
                ].copy()

                upcoming = upcoming.sort_values(
                    "parsed_date", na_position="last"
                ).head(50)

                if upcoming.empty:
                    st.warning(
                        "Aucun prochain match trouvé dans "
                        "le fichier de calendrier."
                    )
                else:
                    predictions = []

                    for _, match in upcoming.iterrows():
                        home = str(match["home"])
                        away = str(match["away"])

                        probs = estimate_match(
                            home, away, history, global_probs
                        )

                        best = max(probs, key=probs.get)

                        predictions.append({
                            "Date": (
                                str(match["date"])
                                if pd.notna(match["date"])
                                else "À confirmer"
                            ),
                            "Match": f"{home} - {away}",
                            "Code estimé": best,
                            "Probabilité code 21": (
                                probs["21"] * 100
                            ),
                            "Code 20 (%)": round(
                                probs["20"] * 100, 1
                            ),
                            "Code 21 (%)": round(
                                probs["21"] * 100, 1
                            ),
                            "Code 24 (%)": round(
                                probs["24"] * 100, 1
                            ),
                        })

                    table = pd.DataFrame(predictions)
                    table = table.sort_values(
                        "Probabilité code 21",
                        ascending=False,
                    )

                    st.dataframe(
                        table,
                        use_container_width=True,
                        hide_index=True,
                    )

                    st.download_button(
                        "📥 Télécharger les estimations CSV",
                        table.to_csv(index=False).encode("utf-8"),
                        file_name="20-21_estimations.csv",
                        mime="text/csv",
                    )

            except Exception as exc:
                st.warning(
                    "Historique chargé, mais le calendrier "
                    f"n'a pas pu être récupéré : {exc}"
                )

            if errors:
                st.warning(
                    "Certaines saisons historiques "
                    "n'étaient pas disponibles : "
                    + "; ".join(errors)
                )

            st.caption(
                "Les estimations utilisent les fréquences "
                "historiques du championnat et des équipes. "
                "Le modèle doit encore être évalué sur des "
                "matchs qu'il n'a pas utilisés pour apprendre."
            )

    except Exception as exc:
        st.error(f"Erreur pendant l'analyse : {exc}")

st.divider()
st.caption(
    "20/21 Analytics | Outil expérimental d'analyse "
    "statistique du football."
)
