# app.py

import os
from datetime import date, datetime


import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import geopandas as gpd
import folium
from folium.features import GeoJsonTooltip
from branca.element import Template, MacroElement, Html

from google.cloud import bigquery
from google.oauth2 import service_account

try:
    import tomllib  # py311+
except Exception:
    import tomli as tomllib  # py310 fallback


# -------------------------------------------------------------------
# Streamlit page config
# -------------------------------------------------------------------
st.set_page_config(
    page_title="Automated District / State Map Generator",
    layout="wide",
)


# -------------------------------------------------------------------
# BigQuery client (cached)
# -------------------------------------------------------------------
@st.cache_resource
# def get_bq_client():
#     # Use your existing service account JSON path here
#     credentials = service_account.Credentials.from_service_account_file(
#         r"C:\Users\vinolin.delphin_spic\Documents\Credentials\vinolin_delphin_spicemoney-dwh_new.json"
#     )
#     client = bigquery.Client(credentials=credentials, project=credentials.project_id)
#     return client

# For Python 3.11+, tomllib is built-in. If you are on 3.10 use:  pip install tomli


def _load_sa_from_toml_files():
    """
    Try to read gcp_service_account from a secrets.toml file on disk:
      1) %USERPROFILE%\.streamlit\secrets.toml
      2) <CWD>\.streamlit\secrets.toml
    Returns (dict_or_None, source_str)
    """
    candidates = [
        os.path.join(os.environ.get("USERPROFILE", ""), ".streamlit", "secrets.toml"),
        os.path.join(os.getcwd(), ".streamlit", "secrets.toml"),
    ]
    for path in candidates:
        try:
            if path and os.path.exists(path):
                with open(path, "rb") as f:
                    data = tomllib.load(f)
                sa = data.get("gcp_service_account")
                if sa:
                    # If the TOML table is a plain dict (already parsed), just return it
                    return sa, f"file:{path}"
        except Exception as e:
            # show but keep trying others
            st.sidebar.warning(f"Could not parse secrets at {path}: {e}")
    return None, None




def get_bq_client():
    """
    Build a BigQuery client, trying sources in this order:
      A) st.secrets['gcp_service_account']
      B) secrets.toml on disk (HOME and CWD)
      C) GOOGLE_APPLICATION_CREDENTIALS
      D) Local hardcoded path (your laptop only)
    Returns: (client, source_str)
    """
    # A) Streamlit Secrets (Cloud or local .streamlit/secrets.toml recognized by Streamlit)
    sa_info = None
    try:
        sa_info = st.secrets.get("gcp_service_account", None)
    except Exception:
        sa_info = None

    if sa_info:
        if isinstance(sa_info, str):
            sa_info = json.loads(sa_info)  # if pasted as a raw JSON string
        creds = service_account.Credentials.from_service_account_info(sa_info)
        # return bigquery.Client(credentials=creds, project=creds.project_id), "secrets:gcp_service_account"
        return bigquery.Client(credentials=creds, project=creds.project_id)

    # B) Directly read secrets.toml from disk (HOME and CWD)
    sa_info, src = _load_sa_from_toml_files()
    if sa_info:
        # keys in TOML table are already parsed as a dict
        creds = service_account.Credentials.from_service_account_info(sa_info)
        # return bigquery.Client(credentials=creds, project=creds.project_id), src
        return bigquery.Client(credentials=creds, project=creds.project_id)

    # # C) Env var (local dev)
    # gac = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    # if gac and os.path.exists(gac):
    #     return bigquery.Client(), f"env:GOOGLE_APPLICATION_CREDENTIALS={gac}"

    # # D) Local fallback (only for your laptop)
    # LOCAL_SA_PATH = r"C:\Users\vinolin_delphin_spic\Documents\Credentials\vinolin_delphin_spicemoney-dwh_new.json"
    # if os.path.exists(LOCAL_SA_PATH):
    #     creds = service_account.Credentials.from_service_account_file(LOCAL_SA_PATH)
    #     return bigquery.Client(credentials=creds, project=creds.project_id), f"local:{LOCAL_SA_PATH}"

    raise RuntimeError(
        "No BigQuery credentials found.\n"
        "Place secrets.toml in HOME or CWD, set GOOGLE_APPLICATION_CREDENTIALS, "
        "or update LOCAL_SA_PATH."
    )


# -------------------------------------------------------------------
# Legend + Title helpers (from your notebook, with legend at top-right)
# -------------------------------------------------------------------
def add_title(folium_map, title, metric, geography, month_year, state):
    """
    Add a fixed-position title box at the top-center of the map.
    """
    from datetime import datetime as dt

    date_obj = dt.strptime(month_year, "%Y-%m-%d")
    formatted_date = date_obj.strftime("%B %Y")

    if geography == "State":
        title_text = f"{metric} Distribution - State - {state} ({formatted_date})"
    else:
        title_text = f"{metric} Distribution - National ({formatted_date})"

    title_html = f"""
    <div style="
        position: fixed;
        top: 15px;
        left: 50%;
        transform: translateX(-50%);
        background-color: white;
        padding: 10px 20px;
        font-size: 16px;
        font-weight: bold;
        z-index: 9999;
        border-radius: 5px;
        box-shadow: 2px 2px 5px rgba(0,0,0,0.3);
    ">
        {title_text}
    </div>
    """

    folium_map.get_root().html.add_child(Html(title_html))
    return folium_map


def add_legend(folium_map, metric, color_map):
    """
    Add a fixed-position legend box. (Moved to top-right so it doesn't get cut off.)
    color_map: dict[label -> color]
    """
    legend_html = f"""
    <div style="
        position: fixed;
        top: 80px;
        right: 50px;
        width: 200px;
        background-color: white;
        z-index: 9999;
        font-size: 14px;
        padding: 10px;
        border-radius: 5px;
        box-shadow: 2px 2px 5px rgba(0,0,0,0.3);
    ">
        <strong>Legend: {metric}</strong><br>
    """

    for category, color in color_map.items():
        legend_html += (
            f'<div style="display:flex;align-items:center;margin:5px 0;">'
            f'<div style="width:15px;height:15px;background:{color};margin-right:5px;"></div>'
            f'{category}</div>'
        )

    legend_html += "</div>"

    legend = MacroElement()
    legend._template = Template(f"{{% macro html(this, kwargs) %}}{legend_html}{{% endmacro %}}")
    folium_map.get_root().add_child(legend)
    return folium_map


# -------------------------------------------------------------------
# Core map generation (structure aligned with your notebook)
# -------------------------------------------------------------------
def generate_folium_map(geography, boundary, metric, month_year, annotations, state):
    """
    Main function that:
      - reads boundary shapefile (district or state),
      - pulls metric data from BigQuery,
      - merges into GeoDataFrame,
      - computes bins and colors (predefined or dynamic),
      - builds Folium map with legend & title.

    Returns:
      folium_map, file_name
    """
    client = get_bq_client()

    # 1. Choose shapefile
    if boundary == "district_level":
        shape_file = "India_District_Boundaries.shp"
    elif boundary == "state_level":
        shape_file = "India_State_Boundaries3.shp"
    else:
        raise ValueError("Invalid boundary type. Choose 'district_level' or 'state_level'.")

    gdf = gpd.read_file(shape_file)

    # 2. Month string for table names (e.g. 'oct_25')
    month_str = pd.to_datetime(month_year).strftime("%b_%Y").lower()

    merged_gdf = None

    # ------------------------------------------------------------------
    # 3. Metric-specific BigQuery logic
    # ------------------------------------------------------------------

    if metric == "DISTRIBUTOR_COMMISSION":
        if boundary == "state_level":
            q = f"""
            SELECT STATE AS STATE_NAME,
                   SUM(COALESCE(TOTAL_DISTR_COMMISSION, 0)) AS DISTRIBUTOR_COMMISSION
            FROM `spicemoney-dwh.analytics_dwh.new_district_monthly_timeline`
            WHERE MONTH_YEAR = '{month_year}'
            GROUP BY STATE
            """
            df = client.query(q).result().to_dataframe()
            merged_gdf = gdf.merge(df, left_on="STATE_NAME", right_on="STATE_NAME", how="left")

        elif boundary == "district_level":
            q = f"""
            SELECT DISTRICT_NAME,
                   STATE AS STATE_x,
                   COALESCE(TOTAL_DISTR_COMMISSION, 0) AS DISTRIBUTOR_COMMISSION
            FROM `spicemoney-dwh.analytics_dwh.new_district_monthly_timeline`
            WHERE MONTH_YEAR = '{month_year}'
            """
            df = client.query(q).result().to_dataframe()
            merged_gdf = gdf.merge(df, left_on="District", right_on="DISTRICT_NAME", how="left")

    elif metric == "AVG_DISTR_COMMISSION":
        if boundary == "state_level":
            q = f"""
            SELECT STATE AS STATE_NAME,
                   ROUND(AVG(COALESCE(TOTAL_DISTR_COMMISSION, 0)), 0) AS AVG_DISTR_COMMISSION
            FROM `spicemoney-dwh.analytics_dwh.new_district_monthly_timeline`
            WHERE MONTH_YEAR = '{month_year}'
            GROUP BY STATE
            """
            df = client.query(q).result().to_dataframe()
            merged_gdf = gdf.merge(df, left_on="STATE_NAME", right_on="STATE_NAME", how="left")

        elif boundary == "district_level":
            # NOTE: This query is based on your screenshot; please paste your exact SQL if needed.
            q = f"""
            SELECT t1.DISTRICT AS DISTRICT_NAME,
                   t2.STATE AS STATE_x,
                   AVG_DISTR_COMMISSION
            FROM (
                SELECT DISTRICT,
                       ROUND(AVG_DISTR_COMMISSION, 0) AS AVG_DISTR_COMMISSION
                FROM `spicemoney-dwh.analytics_dwh.district_wise_average_distributor_commission`
                WHERE MONTH_YEAR = '{month_year}'
                GROUP BY DISTRICT
            ) AS t1
            LEFT JOIN (
                SELECT DISTINCT DISTRICT, STATE
                FROM `spicemoney-dwh.analytics_dwh.v_pincode_master`
            ) AS t2
            ON t1.DISTRICT = t2.DISTRICT
            """
            df = client.query(q).result().to_dataframe()
            merged_gdf = gdf.merge(df, left_on="District", right_on="DISTRICT_NAME", how="left")

    elif metric == "CHANGE_IN_AEPS_MARKET_SHARE":
        table_name = f"spicemoney-dwh.analytics_dwh.sm_business_review_{month_str}"
        if boundary == "state_level":
            # NOTE: Please replace with your exact SQL if any column names differ.
            q = f"""
            SELECT *,
                   ROUND((input_month_ms - apr24_month_ms) * 100, 2) AS CHANGE_IN_AEPS_MARKET_SHARE
            FROM (
                SELECT a.STATE_NAME,
                       a.SM_AEPS_MARKET_SHARE AS input_month_ms,
                       b.SM_AEPS_MARKET_SHARE AS apr24_month_ms
                FROM (
                    SELECT STATE AS STATE_NAME,
                           SAFE_DIVIDE(SAFE_DIVIDE(AEPS_GTV, 1e6), AEPS_MARKET_SIZE) AS SM_AEPS_MARKET_SHARE
                    FROM `{table_name}`
                    GROUP BY STATE
                ) AS a
                LEFT JOIN (
                    SELECT STATE AS STATE_NAME,
                           SAFE_DIVIDE(SAFE_DIVIDE(AEPS_GTV, 1e6), AEPS_MARKET_SIZE) AS SM_AEPS_MARKET_SHARE
                    FROM `spicemoney-dwh.analytics_dwh.sm_business_review_apr_2024`
                    GROUP BY STATE
                ) AS b
                ON a.STATE_NAME = b.STATE_NAME
            )
            """
            df = client.query(q).result().to_dataframe()
            merged_gdf = gdf.merge(df, left_on="STATE_NAME", right_on="STATE_NAME", how="left")

        elif boundary == "district_level":
            q = f"""
            SELECT *,
                   ROUND((input_month_ms - apr24_month_ms) * 100, 2) AS CHANGE_IN_AEPS_MARKET_SHARE
            FROM (
                SELECT a.DISTRICT_NAME,
                       a.STATE AS STATE_x,
                       a.SM_AEPS_MARKET_SHARE AS input_month_ms,
                       b.SM_AEPS_MARKET_SHARE AS apr24_month_ms
                FROM `{table_name}` AS a
                LEFT JOIN `spicemoney-dwh.analytics_dwh.sm_business_review_april_2024` AS b
                ON a.DISTRICT_NAME = b.DISTRICT_NAME
            )
            """
            df = client.query(q).result().to_dataframe()
            merged_gdf = gdf.merge(df, left_on="District", right_on="DISTRICT_NAME", how="left")

    elif metric == "BL_DL_COUNT":
        if boundary == "state_level":
            q = f"""
            SELECT state AS STATE_NAME,
                   COUNT(DISTINCT user_id) AS BL_DL_COUNT
            FROM (
                SELECT agent_id AS user_id, district, state
                FROM (
                    SELECT DISTINCT agent_id, agent_name AS user_name, user_role
                    FROM `impact.agent_login`
                    WHERE user_role NOT IN ('testing','Technology & Research')
                    AND user_role IN ('District Lead','Block Lead')
                ) AS t1
                LEFT JOIN (
                    SELECT DISTINCT user_id, district, state
                    FROM `spicemoney-dwh.analytics_dwh.lead_master_pincode`
                    WHERE user_role IN ('District Lead','Block Lead')
                ) AS t2
                ON t1.agent_id = t2.user_id
            )
            GROUP BY state
            """
            df = client.query(q).result().to_dataframe()
            merged_gdf = gdf.merge(df, left_on="STATE_NAME", right_on="STATE_NAME", how="left")

        elif boundary == "district_level":
            q = f"""
            SELECT a.district AS DISTRICT_NAME,
                   a.state AS STATE_x,
                   COALESCE(BL_DL_COUNT, 0) AS BL_DL_COUNT
            FROM (
                SELECT DISTINCT district, state
                FROM `spicemoney-dwh.analytics_dwh.v_pincode_master`
            ) AS a
            LEFT JOIN (
                SELECT district,
                       COUNT(DISTINCT user_id) AS BL_DL_COUNT
                FROM (
                    SELECT agent_id AS user_id, district, state
                    FROM (
                        SELECT DISTINCT agent_id, agent_name AS user_name, user_role
                        FROM `impact.agent_login`
                        WHERE user_role NOT IN ('testing','Technology & Research')
                        AND user_role IN ('District Lead','Block Lead')
                    ) AS t1
                    LEFT JOIN (
                        SELECT DISTINCT user_id, district, state
                        FROM `spicemoney-dwh.analytics_dwh.lead_master_pincode`
                        WHERE user_role IN ('District Lead','Block Lead')
                    ) AS t2
                    ON t1.agent_id = t2.user_id
                )
                GROUP BY district
            ) AS b
            ON a.district = b.district
            """
            df = client.query(q).result().to_dataframe()
            merged_gdf = gdf.merge(df, left_on="District", right_on="DISTRICT_NAME", how="left")

    elif metric == "ACTIVE_PARTNERS":
        if boundary == "state_level":
            q = f"""
            -- NOTE: Active partner query adapted from your screenshot; paste your exact SQL if needed.
            SELECT a.state AS STATE_NAME,
                   COALESCE(ACTIVE_PARTNERS, 0) AS ACTIVE_PARTNERS
            FROM (
                SELECT DISTINCT district, state
                FROM `spicemoney-dwh.analytics_dwh.v_pincode_master`
            ) AS a
            LEFT JOIN (
                SELECT state,
                       COUNT(DISTINCT distributor_id) AS ACTIVE_PARTNERS
                FROM (
                    SELECT t1.distributor_id,
                           t2.District,
                           t2.State
                    FROM (
                        SELECT distributor_id,
                               District,
                               TOTAL_COMMISSION
                        FROM `spicemoney-dwh.analytics_dwh.monthly_distributor_commission`
                        WHERE month = '2025-02-01' AND TOTAL_COMMISSION > 0
                    ) AS t1
                    LEFT JOIN (
                        SELECT retailer_id AS distributor_id,
                               final_district AS District,
                               final_state AS State
                        FROM `spicemoney-dwh.analytics_dwh.v_client_pincode`
                        WHERE retailer_id IN (
                            SELECT DISTINCT md_code
                            FROM `spicemoney-dwh.prod_dwh.client_details`
                            WHERE client_type IN ('CME', 'distributor')
                        )
                    ) AS t2
                    ON t1.distributor_id = t2.distributor_id
                ) AS b
                GROUP BY state
            ) AS b
            ON a.state = b.state
            """
            df = client.query(q).result().to_dataframe()
            merged_gdf = gdf.merge(df, left_on="STATE_NAME", right_on="STATE_NAME", how="left")

        elif boundary == "district_level":
            q = f"""
            -- NOTE: district-level Active Partners query; paste your exact SQL if needed.
            SELECT a.district AS DISTRICT_NAME,
                   a.state AS STATE_x,
                   COALESCE(ACTIVE_PARTNERS, 0) AS ACTIVE_PARTNERS
            FROM (
                SELECT DISTINCT district, state
                FROM `spicemoney-dwh.analytics_dwh.v_pincode_master`
            ) AS a
            LEFT JOIN (
                SELECT District,
                       COUNT(DISTINCT distributor_id) AS ACTIVE_PARTNERS
                FROM (
                    SELECT t1.distributor_id,
                           t2.District,
                           t2.State
                    FROM (
                        SELECT distributor_id,
                               District,
                               TOTAL_COMMISSION
                        FROM `spicemoney-dwh.analytics_dwh.monthly_distributor_commission`
                        WHERE month = '2025-02-01' AND TOTAL_COMMISSION > 0
                    ) AS t1
                    LEFT JOIN (
                        SELECT retailer_id AS distributor_id,
                               final_district AS District,
                               final_state AS State
                        FROM `spicemoney-dwh.analytics_dwh.v_client_pincode`
                        WHERE retailer_id IN (
                            SELECT DISTINCT md_code
                            FROM `spicemoney-dwh.prod_dwh.client_details`
                            WHERE client_type IN ('CME', 'distributor')
                        )
                    ) AS t2
                    ON t1.distributor_id = t2.distributor_id
                ) AS b
                GROUP BY District
            ) AS b
            ON a.district = b.district
            """
            df = client.query(q).result().to_dataframe()
            merged_gdf = gdf.merge(df, left_on="District", right_on="DISTRICT_NAME", how="left")

    else:
        # ------------------------------------------------------------------
        # Generic branch: any metric from sm_business_review tables
        # ------------------------------------------------------------------
        if boundary == "state_level":
            table_name = f"spicemoney-dwh.analytics_dwh.sm_business_review_{month_str}"
            q = f"""
            SELECT *,
                   SAFE_DIVIDE(SAFE_DIVIDE(AEPS_GTV, 1e6), AEPS_MARKET_SIZE) AS SM_AEPS_MARKET_SHARE
            FROM (
                SELECT STATE AS STATE_NAME,
                       SUM(AEPS_GTV) AS AEPS_GTV,
                       SUM(CMS_GTV) AS CMS_GTV,
                       SUM(BBPS_EMI_GTV) AS BBPS_EMI_GTV,
                       SUM(MATM_GTV) AS MATM_GTV,
                       SUM(DMT_GTV) AS DMT_GTV,
                       SUM(CASA_ACCOUNTS_OPENED) AS CASA_ACCOUNTS_OPENED,
                       SUM(TOTAL_GTV) AS TOTAL_GTV,
                       SUM(TOTAL_IDS_CREATED) AS TOTAL_IDS_CREATED,
                       SUM(TOTAL_UNIQUE_ADHIKARIS) AS TOTAL_UNIQUE_ADHIKARIS,
                       SUM(TOTAL_ACTIVE_ADHIKARIS) AS TOTAL_ACTIVE_ADHIKARIS,
                       SUM(TOTAL_SUSPENDED_ADHIKARIS) AS TOTAL_SUSPENDED_ADHIKARIS,
                       SUM(TRANSACTING_SMAs) AS TRANSACTING_SMAs,
                       SUM(SPGs) AS SPGs,
                       SUM(POTENTIAL_SPGs_non_CMS) AS POTENTIAL_SPGs_non_CMS,
                       SUM(SPs) AS SPs,
                       SUM(SP_WINBACK) AS SP_WINBACK,
                       SUM(POTENTIAL_SPs_non_CMS) AS POTENTIAL_SPs_non_CMS,
                       SUM(BBPS_transacting) AS BBPS_transacting,
                       SUM(BBPS_EMI_transacting) AS BBPS_EMI_transacting,
                       SUM(CASA_TRANSACTING) AS CASA_TRANSACTING,
                       SUM(CASA_5PLUS_ACCOUNTS_TRANSACTING) AS CASA_5PLUS_ACCOUNTS_TRANSACTING,
                       -- add any other fields you use...
                       MAX(month) AS MONTH
                FROM `{table_name}`
                GROUP BY STATE
            )
            """
            df = client.query(q).result().to_dataframe()
            merged_gdf = gdf.merge(df, left_on="STATE_NAME", right_on="STATE_NAME", how="left")

        elif boundary == "district_level":
            table_name = f"spicemoney-dwh.analytics_dwh.sm_business_review_{month_str}"
            q = f"SELECT * FROM `{table_name}`"
            df = client.query(q).result().to_dataframe()
            merged_gdf = gdf.merge(df, left_on="District", right_on="DISTRICT_NAME", how="left")

    if merged_gdf is None:
        raise RuntimeError(f"No data generated for metric: {metric}")

    # ------------------------------------------------------------------
    # 4. Clean types, ensure GeoDataFrame & CRS
    # ------------------------------------------------------------------
    for col in merged_gdf.columns:
        if pd.api.types.is_datetime64_any_dtype(merged_gdf[col]):
            merged_gdf[col] = merged_gdf[col].astype(str)

    if isinstance(merged_gdf.index, pd.DatetimeIndex):
        merged_gdf = merged_gdf.reset_index()

    if not isinstance(merged_gdf, gpd.GeoDataFrame):
        merged_gdf = gpd.GeoDataFrame(merged_gdf)

    if merged_gdf.crs is None:
        merged_gdf.set_crs(epsg=4326, inplace=True)
    merged_gdf = merged_gdf.to_crs(epsg=4326)

    # ------------------------------------------------------------------
    # 5. Predefined bins & colors (from your latest version)
    # ------------------------------------------------------------------
    predefined_metric_bins_district_level = {
        "TRANSACTING_SMAs": (
            # [0, 100, 500, 800, 1200, 2000, np.inf],
            # ["0-100", "100-500", "500-800", "800-1200", "1200-2000", ">2000"],
                 [0, 50, 100, 250, 500, 1000, np.inf],
                ["0-50", "50-100", "100-250", "250-500", "500-1000", ">1000"],
        ),
        "SM_AEPS_MARKET_SHARE": (
            [0, 0.1, 0.14, 0.17, 0.19, 0.21, np.inf],
            ["0-0.1", "0.1-0.14", "0.14-0.17", "0.17-0.19", "0.19-0.21", ">0.21"],
        ),
        "SP_USAGE_CHURN_non_CMS": (
            [0, 1, 2, 3, 4, np.inf],
            ["0-1", "1-2", "2-3", "3-4", ">4"],
        ),
        "CHANGE_IN_AEPS_MARKET_SHARE": (
            [-np.inf, -3, -2, -1, 0, 1, 2, 3, 5, np.inf],
            ["<-3", "-3 to -2", "-2 to -1", "-1 to 0", "0 to 1",
             "1 to 2", "2 to 3", "3 to 4", "4 to 5", ">5"],
        ),
        "BL_DL_COUNT": (
            [0, 1, 2, 3, 4, np.inf],
            ["0", "1", "2", "3", "4", ">4"],
        ),
        "ACTIVE_PARTNERS": (
            [0, 1, 2, 3, 4, np.inf],
            ["0", "1", "2", "3", "4", ">4"],
        ),
    }

    predefined_metric_bins_state_level = {
        "TRANSACTING_SMAs": (
            [0, 2000, 5000, 10000, 20000, 30000, 40000, 50000, np.inf],
            ["0-2000", "2000-5000", "5000-10000", "10000-20000",
             "20000-30000", "30000-40000", "40000-50000", ">50000"],
        ),
        "SM_AEPS_MARKET_SHARE": (
            [0, 0.1, 0.14, 0.17, 0.19, 0.21, np.inf],
            ["0-0.1", "0.1-0.14", "0.14-0.17", "0.17-0.19", "0.19-0.21", ">0.21"],
        ),
        "SP_USAGE_CHURN_non_CMS": (
            [0, 50, 100, 200, 300, np.inf],
            ["0-50", "50-100", "100-200", "200-300", ">300"],
        ),
        "CHANGE_IN_AEPS_MARKET_SHARE": (
            [-np.inf, -3, -2, -1, 0, 1, 2, 3, 5, np.inf],
            ["<-3", "-3 to -2", "-2 to -1", "-1 to 0", "0 to 1",
             "1 to 2", "2 to 3", "3 to 4", "4 to 5", ">5"],
        ),
        "BL_DL_COUNT": (
            [0, 1, 2, 3, 4, np.inf],
            ["0", "1", "2", "3", "4", ">4"],
        ),
        "ACTIVE_PARTNERS": (
            [0, 1, 2, 3, 4, np.inf],
            ["0", "1", "2", "3", "4", ">4"],
        ),
    }

    predefined_metric_colors_district_level = {
        "TRANSACTING_SMAs": {
            "0-50": "darkred",
            "50-100": "red",
            "100-250": "orange",
            "250-500": "#c7e77f",
            "500-1000": "yellowgreen",
            ">1000": "green",
        },
        "SM_AEPS_MARKET_SHARE": {
            "0-0.1": "darkred",
            "0.1-0.14": "red",
            "0.14-0.17": "orange",
            "0.17-0.19": "yellow",
            "0.19-0.21": "lightgreen",
            ">0.21": "green",
        },
        "SP_USAGE_CHURN_non_CMS": {
            "0-1": "green",
            "1-2": "lightgreen",
            "2-3": "yellow",
            "3-4": "orange",
            ">4": "red",
        },
        "CHANGE_IN_AEPS_MARKET_SHARE": {
            "<-3": "darkred",
            "-3 to -2": "darkred",
            "-2 to -1": "red",
            "-1 to 0": "orange",
            "0 to 1": "yellow",
            "1 to 2": "lightgreen",
            "2 to 3": "green",
            "3 to 4": "green",
            "4 to 5": "darkgreen",
            ">5": "darkgreen",
        },
        "BL_DL_COUNT": {
            "0": "grey",
            "1": "lightyellow",
            "2": "yellow",
            "3": "yellowgreen",
            "4": "green",
            ">4": "darkgreen",
        },
        "ACTIVE_PARTNERS": {
            "0": "grey",
            "1": "red",
            "2": "orange",
            "3": "yellow",
            "4": "lightgreen",
            ">4": "green",
        },
    }

    predefined_metric_colors_state_level = {
        "TRANSACTING_SMAs": {
            "0-2000": "darkred",
            "2000-5000": "red",
            "5000-10000": "orangered",
            "10000-20000": "orange",
            "20000-30000": "yellow",
            "30000-40000": "lightgreen",
            "40000-50000": "green",
            ">50000": "green",
        },
        "SM_AEPS_MARKET_SHARE": {
            "0-0.1": "darkred",
            "0.1-0.14": "red",
            "0.14-0.17": "orange",
            "0.17-0.19": "yellow",
            "0.19-0.21": "lightgreen",
            ">0.21": "green",
        },
        "SP_USAGE_CHURN_non_CMS": {
            "0-50": "green",
            "50-100": "lightgreen",
            "100-200": "yellow",
            "200-300": "orange",
            ">300": "red",
        },
        "CHANGE_IN_AEPS_MARKET_SHARE": {
            "<-3": "darkred",
            "-3 to -2": "darkred",
            "-2 to -1": "red",
            "-1 to 0": "orange",
            "0 to 1": "yellow",
            "1 to 2": "lightgreen",
            "2 to 3": "green",
            "3 to 4": "green",
            "4 to 5": "darkgreen",
            ">5": "darkgreen",
        },
        "BL_DL_COUNT": {
            "0": "grey",
            "1": "lightyellow",
            "2": "yellow",
            "3": "yellowgreen",
            "4": "green",
            ">4": "darkgreen",
        },
        "ACTIVE_PARTNERS": {
            "0": "grey",
            "1": "red",
            "2": "orange",
            "3": "yellow",
            "4": "lightgreen",
            ">4": "green",
        },
    }

    if boundary == "district_level":
        metric_list_to_be_used = predefined_metric_bins_district_level
        color_map_to_be_used = predefined_metric_colors_district_level
    else:
        metric_list_to_be_used = predefined_metric_bins_state_level
        color_map_to_be_used = predefined_metric_colors_state_level

    # Cut GeoDataFrame by state if geography == "State"
    if geography == "State":
        merged_gdf = merged_gdf[merged_gdf["STATE_x"] == state]

    # Helper: dynamic bins if metric not predefined
    def get_valid_bins(df, column, bin_options=(10, 5, 4, 3, 2)):
        """
        Try different quantile bin counts until qcut works.
        Returns (df_with_bucket_column, color_map).
        """
        import seaborn as sns

        for q in bin_options:
            try:
                bins, bin_edges = pd.qcut(df[column], q=q, retbins=True, duplicates="raise")
                labels = [f"{int(bin_edges[i])}-{int(bin_edges[i+1])}" for i in range(len(bin_edges) - 1)]
                df["Buckets"] = pd.qcut(df[column], q=q, labels=labels, duplicates="raise")
                num_bins = len(labels)
                dynamic_colors = sns.color_palette("RdYlGn", num_bins).as_hex()
                color_map = {label: dynamic_colors[i] for i, label in enumerate(labels)}
                df["color"] = df["Buckets"].map(color_map)
                return df, color_map
            except ValueError:
                continue

        return df, {}

    # Apply bins and colors
    if metric in metric_list_to_be_used:
        bins, labels = metric_list_to_be_used[metric]
        bins = sorted(bins)
        merged_gdf["Buckets"] = pd.cut(
            merged_gdf[metric],
            bins=bins,
            labels=labels,
            duplicates="drop",
            ordered=False,
        )
        color_map = color_map_to_be_used[metric]
    else:
        merged_gdf, color_map = get_valid_bins(merged_gdf, metric)

    # Some metrics had MONTH column used only for query – drop for most metrics
    if metric not in (
        "DISTRIBUTOR_COMMISSION",
        "AVG_DISTR_COMMISSION",
        "CHANGE_IN_AEPS_MARKET_SHARE",
        "BL_DL_COUNT",
        "ACTIVE_PARTNERS",
    ):
        if "MONTH" in merged_gdf.columns:
            merged_gdf = merged_gdf.drop("MONTH", axis=1)


    print("DEBUG merged_gdf rows:", len(merged_gdf))
    print("DEBUG merged_gdf columns:", merged_gdf.columns.tolist())
    print("DEBUG sample:", merged_gdf.head())

    # ------------------------------------------------------------------
    # 6. Build Folium map
    # ------------------------------------------------------------------

    # Center of map using merged_gdf
    center = [
        merged_gdf.geometry.centroid.y.mean(),
        merged_gdf.geometry.centroid.x.mean(),
    ]
    folium_map = folium.Map(location=center, zoom_start=6, tiles="cartodb positron")

    def style_function(feature):
        bucket = feature["properties"].get("Buckets", "gray")
        return {
            "fillColor": color_map.get(bucket, "gray"),
            "color": "black",
            "weight": 1,
            "fillOpacity": 1,
            #  tiles="cartodb positron",
            #  zoom_start=6,
            #  location=center

        }

    # Tooltip fields depend on boundary, but the data source is ALWAYS merged_gdf
    if boundary == "state_level":
        tooltip_fields = ["STATE_NAME", metric, "Buckets"]
        tooltip_aliases = ["State:", metric, "Category:"]
    else:  # 'district_level'
        tooltip_fields = ["DISTRICT_NAME", metric, "Buckets"]
        tooltip_aliases = ["District:", metric, "Category:"]

    folium.GeoJson(
        merged_gdf,                           # <-- ALWAYS merged_gdf
        name=metric,
        style_function=style_function,
        tooltip=GeoJsonTooltip(
            fields=tooltip_fields,
            aliases=tooltip_aliases,
            localize=True,
            sticky=False,
            labels=True,
            style="background-color: white; color: black; font-weight: bold;",
        ),
    ).add_to(folium_map)

    # center = [merged_gdf.geometry.centroid.y.mean(), merged_gdf.geometry.centroid.x.mean()]
    # folium_map = folium.Map(location=center, zoom_start=6, tiles="cartodb positron")

    # def style_function(feature):
    #     bucket = feature["properties"].get("Buckets", "gray")
    #     return {
    #         "fillColor": color_map.get(bucket, "gray"),
    #         "color": "black",
    #         "weight": 1,
    #         "fillOpacity": 1,
    #     }

    # if boundary == "state_level":
    #     folium.GeoJson(
    #         merged_gdf,
    #         name=metric,
    #         style_function=style_function,
    #         tooltip=GeoJsonTooltip(
    #             fields=["STATE_NAME", metric, "Buckets"],
    #             aliases=["State:", metric, "Category:"],
    #             localize=True,
    #             sticky=False,
    #             labels=True,
    #             style="background-color: white; color: black; font-weight: bold;",
    #         ),
    #     ).add_to(folium_map)
    # else:
    #     folium.GeoJson(
    #         merged_gdf,
    #         name=metric,
    #         style_function=style_function,
    #         tooltip=GeoJsonTooltip(
    #             fields=["DISTRICT_NAME", metric, "Buckets"],
    #             aliases=["District:", metric, "Category:"],
    #             localize=True,
    #             sticky=False,
    #             labels=True,
    #             style="background-color: white; color: black; font-weight: bold;",
    #         ),
    #     ).add_to(folium_map)

    # File name for download (but we do NOT save automatically)
    if geography == "State":
        file_name = f"MAP_State_{state}_{boundary}_{metric}_{month_year}.html"
    else:
        file_name = f"MAP_National_{boundary}_{metric}_{month_year}.html"

    # ------------------------------------------------------------------
    # 7. Optional annotations
    # ------------------------------------------------------------------
    if annotations == "YES":
        # Show state or district labels on centroids
        for _, row in merged_gdf.iterrows():
            centroid = row.geometry.centroid
            if boundary == "state_level":
                label = row["STATE_NAME"]
            else:
                label = row["DISTRICT_NAME"]
            folium.Marker(
                location=[centroid.y, centroid.x],
                icon=folium.DivIcon(
                    html=(
                        f'<div style="font-size:10px;font-weight:bold;color:black;">'
                        f"{label}</div>"
                    )
                ),
            ).add_to(folium_map)

    # Legend + Title
    folium_map = add_legend(folium_map, metric, color_map)
    folium_map = add_title(folium_map, "", metric, geography, month_year, state)
    # Add title bar
    # folium_map = add_title(folium_map, metric, geography, month_year, state)

    # Convert to HTML string to show in Streamlit
    # map_html = folium_map._repr_html_()
    # return folium_map, file_name, map_html

    return folium_map, file_name




# ===========================
# STREAMLIT APP (UI + DOWNLOAD)
# ===========================
import streamlit as st
from streamlit_folium import st_folium

# ---- page config ----
st.set_page_config(
    page_title="Automated District / State Map Generator",
    layout="wide",
)

# ---- sidebar: inputs ----
with st.sidebar:
    st.header("Configuration")

    geography = st.selectbox(
        "Select Geography",
        ["State", "National"],
        index=0,
        key="geography",
    )

    boundary = st.selectbox(
        "Select Boundary",
        ["district_level", "state_level"],
        index=0,
        key="boundary",
    )

    metric = st.selectbox(
        "Select Metric",
        [
            "TRANSACTING_SMAs",
            "SM_AEPS_MARKET_SHARE",
            "GROSS_ADDS",
            "NET_ADDS",
            "SP_WINBACK",
            "SP_NEW_ACTIVATIONS_non_CMS",
            "SP_USAGE_CHURN_non_CMS",
            "SPs",
            "BL_DL_COUNT",
            "ACTIVE_PARTNERS",
            "ENGAGED_PARTNERS",
            "DISTRIBUTOR_COMMISSION",
            "AVG_DISTR_COMMISSION",
            "CHANGE_IN_AEPS_MARKET_SHARE",
            # add any other metrics you already have
        ],
        key="metric",
    )

    # Month selection – user sees "October 2025", backend gets "2025-10-01"
    from datetime import datetime

    def _month_label_to_value(label: str) -> str:
        # 'October 2025' -> '2025-10-01'
        dt = datetime.strptime(label, "%B %Y")
        return dt.strftime("%Y-%m-01")

    # build month list from April 2024 to last available month (like you had)
    start_year, start_month = 2024, 4
    today = datetime.today()
    end_year, end_month = today.year, today.month - 1 if today.month > 1 else 12
    if today.month == 1:
        end_year -= 1

    month_labels = []
    y, m = start_year, start_month
    while (y < end_year) or (y == end_year and m <= end_month):
        month_labels.append(datetime(y, m, 1).strftime("%B %Y"))  # e.g. "October 2025"
        if m == 12:
            y += 1
            m = 1
        else:
            m += 1

    selected_month_label = st.selectbox(
        "Select Month–Year",
        month_labels,
        index=len(month_labels) - 1,
        key="month_year_label",
    )
    # this is the exact string your queries expect (YYYY-MM-01)
    month_year = _month_label_to_value(selected_month_label)

    annotations = st.selectbox(
        "Need Annotations?",
        ["YES", "NO"],
        index=0,
        key="annotations",
    )

    # state dropdown only when geography == "State"
    state = None
    if geography == "State":
        state = st.selectbox(
            "Select State",
            [
                "TAMIL NADU",
                "UTTAR PRADESH",
                "BIHAR",
                "WEST BENGAL",
                "MADHYA PRADESH",
                "MAHARASHTRA",
                "KARNATAKA",
                "ODISHA",
                "CHHATTISGARH",
                "JHARKHAND",
                "PUNJAB",
                "DELHI_NCR",
                "HARYANA",
                # add any other states you included in Tkinter
            ],
            key="state",
        )
    else:
        state = "N/A"

    generate_clicked = st.button("Generate Map", type="primary")


# ---- header (title + download button) ----
col1, col2 = st.columns([4, 1])

with col1:
    st.title("🗺️ Automated District / State Map Generator")

with col2:
    map_ready = "map_file_bytes" in st.session_state

    if map_ready:
        clicked_download = st.download_button(
            label="⬇️ Download HTML Map",
            data=st.session_state["map_file_bytes"],
            file_name=st.session_state.get("map_file_name", "map.html"),
            mime="text/html",
            use_container_width=True,
            key="download_html_map",
        )
        if clicked_download:
            st.success("Map download started.")
    else:
        # show disabled button in same place until a map is generated
        st.download_button(
            label="⬇️ Download HTML Map",
            data=b"",
            file_name="map.html",
            mime="text/html",
            disabled=True,
            use_container_width=True,
            key="download_html_map_disabled",
        )


# ---- main map area ----
map_container = st.container()

if generate_clicked:
    with st.spinner("Generating map… this may take a few seconds"):
        try:
        # IMPORTANT: this uses your existing function & logic
            folium_map, file_name = generate_folium_map(
                geography=geography,
                boundary=boundary,
                metric=metric,
                month_year=month_year,
                annotations=annotations,
                state=state,
            )

            # render map HTML once and store for download + display
            map_html = folium_map.get_root().render()
            st.session_state["map_file_bytes"] = map_html.encode("utf-8")
            st.session_state["map_file_name"] = file_name
            st.session_state["map_html"] = map_html
        except Exception as e:
            st.error(f"❌ Error while generating map: {e}")
            # Stop this run so spinner finishes and we don’t get half-rendered UI
            st.stop()

        with map_container:
            st_folium(folium_map, width=None, height=650)

# elif "map_file_bytes" in st.session_state:
# #     pass
#     # if user already generated a map earlier in the session, keep showing it
#     # from folium import Map
#     # from branca.element import Figure

#     # rebuild folium Map from stored HTML
#     # easiest is to re-run generate_folium_map if you want "remembered" values,
#     # but to keep it simple we'll only display after generate until page reload
#     folium_map, _ = generate_folium_map(
#         geography=geography,
#         boundary=boundary,
#         metric=metric,
#         month_year=month_year,
#         annotations=annotations,
#         state=state,
#     )
#     with map_container:
#         st_folium(folium_map, width=None, height=650)

# --- 2. display the last generated map (no extra processing) ---

if "map_html" in st.session_state:
    st.components.v1.html(
        st.session_state["map_html"],
        height=650,
        width=None,
    )