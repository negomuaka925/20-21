
import streamlit as st
import pandas as pd
import requests
from datetime import date, timedelta

st.set_page_config(
    page_title="20/21 Analytics",
    page_icon="⚽",
    layout="wide",
)

API_BASE = "https://v3.football.api-sports.io"
TZ = "Africa/Kinshasa"

st.title("⚽ 20/21 Analytics")
st.caption(
    "Calendrier multi-compétitions et estimation statistique "
    "des codes 20, 21 et 24."
)

st.info(
    "Code 20 : davantage de buts en 1re mi-temps. "
    "Code 21 : davantage de buts en 2e mi-temps. "
    "Code 24 : même nombre de buts dans les deux mi-temps. "
    "Les probabilités sont indicatives et ne garantissent aucun résultat."
)


def get_api_key():
    try:
        return st.secrets["API_SPORTS_KEY"]
    except Exception:
        return ""


@st.cache_data(ttl=1800, show_spinner=False)
def api_get(endpoint, params_tuple, api_key):
    params = dict(params_tuple)
    response = requests.get(
        f"{API_BASE}/{endpoint}",
        headers={"x-apisports-key": api_key},
        params=params,
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()

    if payload.get("errors"):
        raise RuntimeError(str(payload["errors"]))

    return payload.get("response", [])


def request_data(endpoint, params, api_key):
    return api_get(
        endpoint,
        tuple(sorted(params.items())),
        api_key,
    )


def extract_code(fixture):
    scores = fixture.get("score") or {}
    halftime = scores.get("halftime") or {}
    fulltime = scores.get("fulltime") or {}

    ht_home = halftime.get("home")
    ht_away = halftime.get("away")
    ft_home = fulltime.get("home")
    ft_away = fulltime.get("away")

    if None in (ht_home, ht_away, ft_home, ft_away):
        return None

    first_half = ht_home + ht_away
    second_half = (ft_home + ft_away) - first_half

    if second_half < 0:
        return None
    if second_half > first_half:
        return "21"
    if first_half > second_half:
        return "20"
    return "24"


def fixture_row(item):
    league = item.get("league") or {}
    teams = item.get("teams") or {}
    fixture = item.get("fixture") or {}
    goals = item.get("goals") or {}

    home = (teams.get("home") or {}).get(
        "name", "Équipe domicile"
    )
    away = (teams.get("away") or {}).get(
        "name", "Équipe extérieure"
    )

    return {
        "Date/heure": fixture.get("date"),
        "Pays": league.get("country", ""),
        "Compétition": league.get("name", ""),
        "Journée / tour": league.get("round", ""),
        "Match": f"{home} - {away}",
        "Domicile": home,
        "Extérieur": away,
        "Statut": (fixture.get("status") or {}).get("long", ""),
        "Score": (
            f'{goals.get("home") if goals.get("home") is not None else "-"}'
            f' - {goals.get("away") if goals.get("away") is not None else "-"}'
        ),
        "Ligue ID": league.get("id"),
        "Saison": league.get("season"),
    }


def code_probabilities(codes, prior=None, strength=8):
    keys = ["20", "21", "24"]

    if prior is None:
        prior = {
            "20": 1 / 3,
            "21": 1 / 3,
            "24": 1 / 3,
        }

    counts = pd.Series(list(codes)).value_counts()
    total = int(counts.sum())
    denominator = total + strength

    return {
        key: (
            int(counts.get(key, 0)) + strength * prior[key]
        ) / denominator
        for key in keys
    }


@st.cache_data(ttl=3600, show_spinner=False)
def get_leagues(api_key, season):
    return request_data(
        "leagues",
        {"season": season},
        api_key,
    )


@st.cache_data(ttl=3600, show_spinner=False)
def get_league_history(league_id, season, api_key):
    items = request_data(
        "fixtures",
        {
            "league": int(league_id),
            "season": int(season),
            "timezone": TZ,
        },
        api_key,
    )

    records = []

    for item in items:
        code = extract_code(item)

        if code:
            teams = item.get("teams") or {}
            fixture = item.get("fixture") or {}

            records.append({
                "code": code,
                "home": (teams.get("home") or {}).get("name", ""),
                "away": (teams.get("away") or {}).get("name", ""),
                "date": fixture.get("date", ""),
            })

    return pd.DataFrame(records)


def estimate_fixture(home, away, history):
    if history.empty:
        return {
            "20": 1 / 3,
            "21": 1 / 3,
            "24": 1 / 3,
        }, 0

    global_prior = code_probabilities(
        history["code"],
        strength=0,
    )

    team_probs = []

    for team in (home, away):
        team_rows = history[
            (history["home"] == team)
            | (history["away"] == team)
        ]

        team_rows = team_rows.sort_values("date").tail(20)

        team_probs.append(
            code_probabilities(
                team_rows["code"],
                global_prior,
                strength=8,
            )
        )

    probs = {
        code: (
            0.50 * global_prior[code]
            + 0.25 * team_probs[0][code]
            + 0.25 * team_probs[1][code]
        )
        for code in ("20", "21", "24")
    }

    total = sum(probs.values())

    return {
        key: value / total
        for key, value in probs.items()
    }, len(history)


api_key = get_api_key()

if not api_key:
    st.warning(
        "Pour activer le calendrier élargi, ajoute ta clé API-Sports "
        "dans les secrets Streamlit sous le nom API_SPORTS_KEY. "
        "Ne colle jamais cette clé dans le code ni dans cette conversation."
    )
    st.markdown(
        "Documentation : https://www.api-football.com/documentation-v3"
    )
    st.stop()


with st.sidebar:
    st.header("Filtres")

    today = date.today()

    start_date = st.date_input(
        "Du",
        value=today,
    )

    end_date = st.date_input(
        "Au",
        value=today + timedelta(days=7),
        min_value=start_date,
    )

    season = st.selectbox(
        "Saison",
        [2026, 2025, 2024],
        index=0,
    )

    country_filter = st.text_input(
        "Pays (facultatif)",
        placeholder="Ex. England, France",
    )

    league_search = st.text_input(
        "Compétition (facultatif)",
        placeholder="Ex. Premier League",
    )

    today_only = st.checkbox(
        "Afficher uniquement les matchs d'aujourd'hui",
        value=False,
    )

    analyze = st.button(
        "🔎 Charger et analyser les matchs",
        type="primary",
        use_container_width=True,
    )


if analyze:
    if end_date < start_date:
        st.error(
            "La date de fin doit être égale ou postérieure "
            "à la date de début."
        )
        st.stop()

    if (end_date - start_date).days > 14:
        st.warning(
            "Pour limiter les appels API, sélectionne "
            "une période de 14 jours maximum."
        )
        st.stop()

    try:
        with st.spinner(
            "Récupération des matchs et des compétitions..."
        ):
            fixtures = request_data(
                "fixtures",
                {
                    "from": start_date.isoformat(),
                    "to": end_date.isoformat(),
                    "timezone": TZ,
                },
                api_key,
            )

        rows = [fixture_row(item) for item in fixtures]

        if not rows:
            st.warning(
                "Aucun match retourné pour cette période. "
                "Vérifie les dates et les droits de ton abonnement API."
            )
            st.stop()

        df = pd.DataFrame(rows)

        df["Date/heure"] = pd.to_datetime(
            df["Date/heure"],
            errors="coerce",
            utc=True,
        )

        df["Date locale"] = (
            df["Date/heure"]
            .dt.tz_convert(TZ)
            .dt.strftime("%Y-%m-%d")
        )

        df["Heure locale"] = (
            df["Date/heure"]
            .dt.tz_convert(TZ)
            .dt.strftime("%H:%M")
        )

        if today_only:
            df = df[
                df["Date locale"] == date.today().isoformat()
            ]

        if country_filter.strip():
            df = df[
                df["Pays"].str.contains(
                    country_filter.strip(),
                    case=False,
                    na=False,
                )
            ]

        if league_search.strip():
            df = df[
                df["Compétition"].str.contains(
                    league_search.strip(),
                    case=False,
                    na=False,
                )
            ]

        df = df.sort_values(
            ["Date locale", "Heure locale", "Compétition"],
            na_position="last",
        )

        if df.empty:
            st.warning(
                "Aucun match ne correspond aux filtres sélectionnés."
            )
            st.stop()

        st.success(
            f"{len(df)} match(s) trouvé(s) dans la période sélectionnée."
        )

        st.subheader("📅 Calendrier des matchs")

        view = df[
            [
                "Date locale",
                "Heure locale",
                "Pays",
                "Compétition",
                "Journée / tour",
                "Match",
                "Statut",
                "Score",
            ]
        ].copy()

        st.dataframe(
            view,
            use_container_width=True,
            hide_index=True,
        )

        st.subheader("📊 Estimations du marché 20/21")

        st.caption(
            "Les estimations sont calculées pour les compétitions "
            "dont l'API renvoie un historique exploitable. "
            "Les matchs sans données suffisantes reçoivent "
            "une estimation neutre."
        )

        predictions = []

        unique_leagues = df[
            ["Ligue ID", "Saison", "Compétition"]
        ].drop_duplicates()

        history_cache = {}
        progress = st.progress(0)
        total_leagues = max(len(unique_leagues), 1)

        for i, (_, league_row) in enumerate(
            unique_leagues.iterrows(),
            start=1,
        ):
            league_id = league_row["Ligue ID"]
            league_season = league_row["Saison"]

            try:
                history_cache[(league_id, league_season)] = (
                    get_league_history(
                        int(league_id),
                        int(league_season),
                        api_key,
                    )
                )
            except Exception:
                history_cache[(league_id, league_season)] = (
                    pd.DataFrame()
                )

            progress.progress(i / total_leagues)

        for _, match in df.iterrows():
            hist = history_cache.get(
                (match["Ligue ID"], match["Saison"]),
                pd.DataFrame(),
            )

            probs, history_n = estimate_fixture(
                match["Domicile"],
                match["Extérieur"],
                hist,
            )

            best = max(probs, key=probs.get)

            predictions.append({
                "Date locale": match["Date locale"],
                "Heure locale": match["Heure locale"],
                "Compétition": match["Compétition"],
                "Match": match["Match"],
                "Code estimé": best,
                "Code 20 (%)": round(probs["20"] * 100, 1),
                "Code 21 (%)": round(probs["21"] * 100, 1),
                "Code 24 (%)": round(probs["24"] * 100, 1),
                "Matchs historiques utilisés": history_n,
            })

        result = pd.DataFrame(predictions)

        result = result.sort_values(
            ["Date locale", "Heure locale", "Code 21 (%)"],
            ascending=[True, True, False],
        )

        st.dataframe(
            result,
            use_container_width=True,
            hide_index=True,
        )

        st.download_button(
            "📥 Télécharger les estimations CSV",
            result.to_csv(index=False).encode("utf-8"),
            file_name="20-21_estimations.csv",
            mime="text/csv",
        )

        st.caption(
            "La couverture dépend de ton abonnement et des compétitions "
            "disponibles chez le fournisseur. Les estimations ne constituent "
            "pas un conseil de pari."
        )

    except requests.HTTPError as exc:
        status = getattr(
            exc.response,
            "status_code",
            "inconnu",
        )

        st.error(
            f"Erreur HTTP {status} lors de l'appel à l'API. "
            "Vérifie la clé, les droits de ton abonnement "
            "et les limites d'appels."
        )

    except Exception as exc:
        st.error(
            f"Impossible de charger les matchs : {exc}"
        )


st.divider()

st.caption(
    "20/21 Analytics | Version expérimentale | Fuseau horaire : Kinshasa"
)
