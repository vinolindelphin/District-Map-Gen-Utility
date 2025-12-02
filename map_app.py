# app.py
# ============================================================
# Automated District / State Map Generator - Streamlit Version
# ============================================================

import os
import warnings
from datetime import date, datetime

import numpy as np
import pandas as pd
import geopandas as gpd
import folium
from folium.features import GeoJsonTooltip
import seaborn as sns

from google.cloud import bigquery
from google.oauth2 import service_account

from branca.element import Html, MacroElement, Template

import streamlit as st
import streamlit.components.v1 as components


# ------------------------------------------------------------
# Basic setup
# ------------------------------------------------------------
warnings.filterwarnings("ignore")

# Clean any proxy env vars (mirroring your notebook)
for var in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
    os.environ.pop(var, None)

# ------------------------------------------------------------
# BigQuery client
# ------------------------------------------------------------
# Adjust this path to your actual credentials JSON
SERVICE_ACCOUNT_PATH =  r"C:\Users\vinolin.delphin_spic\Documents\Credentials\vinolin_delphin_spicemoney-dwh_new.json"

if os.path.exists(SERVICE_ACCOUNT_PATH):
    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_PATH
    )
    bq_client = bigquery.Client(
        credentials=credentials, project=credentials.project_id
    )
else:
    # Fallback to default credentials if service account file not present
    bq_client = bigquery.Client()


# ------------------------------------------------------------
# Title & Legend helpers (from updated code)
# ------------------------------------------------------------
def add_title(folium_map, title, metric, geography, month_year, state):
    """Add a fixed title bar to the Folium map."""
    from datetime import datetime as dt

    date_obj = dt.strptime(month_year, "%Y-%m-%d")
    formatted_date = date_obj.strftime("%B %Y")

    title_html = f"""
    <div style="position: fixed; top: 10px; left: 50%; transform: translateX(-50%);
                background-color: white; padding: 10px; font-size: 16px;
                font-weight: bold; z-index: 9999; border-radius: 5px;
                box-shadow: 2px 2px 5px rgba(0,0,0,0.3);">
        {metric} Distribution - {geography} - {state} ({formatted_date})
    </div>
    """

    folium_map.get_root().html.add_child(folium.Element(title_html))
    return folium_map


def add_legend(folium_map, metric, color_map):
    legend_html = f"""
    <div style="
        position: fixed;
        top: 80px;
        right: 50px;
        width: 220px;
        height: auto;
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
            "<div style='display: flex; align-items: center; margin: 5px 0;'>"
            f"<div style='width: 15px; height: 15px; background:{color}; margin-right: 5px;'></div>"
            f"{category}</div>"
        )

    legend_html += "</div>"

    legend = MacroElement()
    legend._template = Template(
        f"""
        {{% macro html(this, kwargs) %}}
        {legend_html}
        {{% endmacro %}}
        """
    )

    folium_map.get_root().add_child(legend)
    return folium_map


# def add_legend(folium_map, metric, color_map):
#     """Add a fixed legend box based on color_map."""
#     legend_html = f"""
#     <div style="
#         position: fixed;
#         bottom: 50px;
#         left: 50px;
#         width: 220px;
#         height: auto;
#         background-color: white;
#         z-index: 9999;
#         font-size: 14px;
#         padding: 10px;
#         border-radius: 5px;
#         box-shadow: 2px 2px 5px rgba(0,0,0,0.3);
#     ">
#     <strong>Legend: {metric}</strong><br>
#     """

#     for category, color in color_map.items():
#         legend_html += (
#             "<div style='display: flex; align-items: center; margin: 5px 0;'>"
#             f"<div style='width: 15px; height: 15px; background:{color}; margin-right: 5px;'></div>"
#             f"{category}</div>"
#         )

#     legend_html += "</div>"

#     legend = MacroElement()
#     legend._template = Template(
#         f"""
#         {{% macro html(this, kwargs) %}}
#         {legend_html}
#         {{% endmacro %}}
#         """
#     )

#     folium_map.get_root().add_child(legend)
#     return folium_map


# ------------------------------------------------------------
# Metric bins & colors (updated version)
# ------------------------------------------------------------

# DISTRICT LEVEL BINS
predefined_metric_bins_district_level = {
    "TRANSACTING_SMAs": (
        [0, 100, 500, 800, 1200, 2000, np.inf],
        ["0-50", "50-100", "100-250", "250-500", "500-1000", ">1000"],
    ),
    "SM_AEPS_MARKET_SHARE": (
        [0, 0.1, 0.14, 0.17, 0.19, 0.21, np.inf],
        ["0-0.1", "0.1-0.14", "0.14-0.17", "0.17-0.19", "0.19-0.21", ">0.21"],
    ),
    # Dynamic comments in notebook mentioned these were moved:
    # 'SP_USAGE_CHURN_non_CMS': ([0, 1, 2, 3, 4, np.inf], ['0-1','1-2','2-3','3-4','>4']),
    "CHANGE_IN_AEPS_MARKET_SHARE": (
        [-np.inf, -3, -2, -1, 0, 1, 2, 3, 4, 5, np.inf],
        [
            "<-3",
            "-3 to -2",
            "-2 to -1",
            "-1 to 0",
            "0 to 1",
            "1 to 2",
            "2 to 3",
            "3 to 4",
            "4 to 5",
            ">5",
        ],
    ),
    "BL_DL_COUNT": (
        [-np.inf, 0, 1, 2, 3, 4, np.inf],
        ["0", "1", "2", "3", "4", ">4"],
    ),
    "ACTIVE_PARTNERS": (
        [-np.inf, 0, 1, 2, 3, 4, np.inf],
        ["0", "1", "2", "3", "4", ">4"],
    ),
}

# STATE LEVEL BINS
predefined_metric_bins_state_level = {
    "TRANSACTING_SMAs": (
        [0, 2000, 5000, 10000, 20000, 30000, 40000, 50000, np.inf],
        [
            "0-2000",
            "2000-5000",
            "5000-10000",
            "10000-20000",
            "20000-30000",
            "30000-40000",
            "40000-50000",
            ">50000",
        ],
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
        [-np.inf, -3, -2, -1, 0, 1, 2, 3, 4, 5, np.inf],
        [
            "<-3",
            "-3 to -2",
            "-2 to -1",
            "-1 to 0",
            "0 to 1",
            "1 to 2",
            "2 to 3",
            "3 to 4",
            "4 to 5",
            ">5",
        ],
    ),
}

# DISTRICT LEVEL COLORS
predefined_metric_colors_district_level = {
    "TRANSACTING_SMAs": {
        "0-50": "darkred",
        "50-100": "red",
        "100-250": "orange",
        "250-500": "gold",
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
        "3": "khaki",
        "4": "yellowgreen",
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

# STATE LEVEL COLORS
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
}


# ------------------------------------------------------------
# Helper: dynamic binning (get_valid_bins from notebook)
# ------------------------------------------------------------
def get_valid_bins(df, column, bin_options=[10, 5, 4, 3, 2]):
    """
    Tries different quantile bin options until a valid one is found and
    generates range-based labels with dynamic color mapping (RdYlGn).
    """
    for q in bin_options:
        try:
            # Compute quantile bins
            _, bin_edges = pd.qcut(
                df[column], q=q, retbins=True, duplicates="raise"
            )

            # Generate labels dynamically based on bin edges
            labels = [
                f"{int(bin_edges[i])}-{int(bin_edges[i + 1])}"
                for i in range(len(bin_edges) - 1)
            ]

            # Apply qcut with new labels
            df["Buckets"] = pd.qcut(
                df[column], q=q, labels=labels, duplicates="raise"
            )

            # Generate colors using RdYlGn gradient
            num_bins = len(labels)
            dynamic_colors = sns.color_palette("RdYlGn", num_bins).as_hex()
            color_map = {
                label: dynamic_colors[i] for i, label in enumerate(labels)
            }

            return df, color_map
        except ValueError:
            continue

    # Fallback if all attempts fail
    print("All bin attempts failed. Consider different binning logic.")
    return df, {}


# ------------------------------------------------------------
# Core map-generation function (fully ported)
# ------------------------------------------------------------
def generate_folium_map(geography, boundary, metric, month_year, annotations, state):
    """
    Core logic from your updated notebook.
    geography: 'National' or 'State'
    boundary : 'district_level' or 'state_level'
    metric   : one of your metric options
    month_year: 'YYYY-MM-DD'
    annotations: 'YES' or 'NO'
    state: selected state (string) or 'N/A'
    """

    # If state-level boundaries and geography='State', reset to National (same as notebook)
    if (boundary == "state_level") and (geography == "State"):
        geography = "National"
        print("Resetting geography to NATIONAL")

    # Choose shapefile
    if boundary == "district_level":
        shape_file = "India_District_Boundaries.shp"
    elif boundary == "state_level":
        shape_file = "India_State_Boundaries3.shp"
    else:
        raise ValueError("Invalid boundary type. Choose 'district_level' or 'state_level'.")

    # Load shapefile
    gdf = gpd.read_file(shape_file)

    # Month string for table naming
    month_str = pd.to_datetime(month_year).strftime("%b_%Y").lower()

    # --------------------------------------------
    # Query data from BigQuery
    # --------------------------------------------
    client = bq_client  # use global client

    if metric == "DISTRIBUTOR_COMMISSION":
        # TOTAL DISTRIBUTOR COMMISSION
        if boundary == "state_level":
            q_disr_comm = f"""
            SELECT
              STATE AS STATE_NAME,
              SUM(COALESCE(TOTAL_DISTR_COMMISSION, 0)) AS DISTRIBUTOR_COMMISSION
            FROM `spicemoney-dwh.analytics_dwh.new_district_monthly_timeline`
            WHERE MONTH_YEAR = '{month_year}'
            GROUP BY STATE
            """
            df = client.query(q_disr_comm).result().to_dataframe()
            merged_gdf = gdf.merge(df, left_on="STATE_NAME", right_on="STATE_NAME", how="left")

        elif boundary == "district_level":
            q_disr_comm = f"""
            SELECT
              DISTRICT_NAME,
              STATE AS STATE_x,
              COALESCE(TOTAL_DISTR_COMMISSION, 0) AS DISTRIBUTOR_COMMISSION
            FROM `spicemoney-dwh.analytics_dwh.new_district_monthly_timeline`
            WHERE MONTH_YEAR = '{month_year}'
            """
            df = client.query(q_disr_comm).result().to_dataframe()
            merged_gdf = gdf.merge(df, left_on="District", right_on="DISTRICT_NAME", how="left")

        else:
            raise ValueError("Invalid boundary for DISTRIBUTOR_COMMISSION")

    elif metric == "AVG_DISTR_COMMISSION":
        # AVERAGE DISTRIBUTOR COMMISSION
        if boundary == "state_level":
            q_disr_comm = f"""
            SELECT
              STATE AS STATE_NAME,
              ROUND(AVG(COALESCE(TOTAL_DISTR_COMMISSION, 0)), 0) AS AVG_DISTR_COMMISSION
            FROM `spicemoney-dwh.analytics_dwh.new_district_monthly_timeline`
            WHERE MONTH_YEAR = '{month_year}'
            GROUP BY STATE
            """
            df = client.query(q_disr_comm).result().to_dataframe()
            merged_gdf = gdf.merge(df, left_on="STATE_NAME", right_on="STATE_NAME", how="left")

        elif boundary == "district_level":
            q_disr_comm = f"""
            SELECT
              t1.DISTRICT AS DISTRICT_NAME,
              t2.state AS STATE_x,
              AVG_DISTR_COMMISSION
            FROM (
                SELECT
                  DISTRICT,
                  ROUND(AVG_DISTR_COMMISSION, 0) AS AVG_DISTR_COMMISSION
                FROM `spicemoney-dwh.analytics_dwh.district_wise_average_distributor_commission`
                WHERE month_year = '{month_year}'
            ) AS t1
            LEFT JOIN (
                SELECT DISTINCT district, state
                FROM `spicemoney-dwh.analytics_dwh.v_pincode_master`
            ) AS t2
            ON t1.DISTRICT = t2.district
            """
            df = client.query(q_disr_comm).result().to_dataframe()
            merged_gdf = gdf.merge(df, left_on="District", right_on="DISTRICT_NAME", how="left")

        else:
            raise ValueError("Invalid boundary for AVG_DISTR_COMMISSION")

    elif metric == "CHANGE_IN_AEPS_MARKET_SHARE":
        # CHANGE IN AEPS MARKET SHARE vs Apr 2024
        table_name = f"`spicemoney-dwh.analytics_dwh.sm_business_review_{month_str}`"

        if boundary == "state_level":
            q_aeps_change = f"""
            SELECT
              *,
              ROUND((input_month_ms - apr24_month_ms) * 100, 2) AS CHANGE_IN_AEPS_MARKET_SHARE
            FROM (
              SELECT
                a.STATE_NAME,
                a.SM_AEPS_MARKET_SHARE AS input_month_ms,
                b.SM_AEPS_MARKET_SHARE AS apr24_month_ms
              FROM (
                SELECT
                  STATE AS STATE_NAME,
                  SAFE_DIVIDE(SAFE_DIVIDE(AEPS_GTV, 1e6), AEPS_MARKET_SIZE) AS SM_AEPS_MARKET_SHARE
                FROM (
                  SELECT
                    STATE AS STATE_NAME,
                    SUM(AEPS_GTV) AS AEPS_GTV,
                    SUM(AEPS_MARKET_SIZE) AS AEPS_MARKET_SIZE,
                    MAX(month) AS MONTH
                  FROM {table_name}
                  GROUP BY state
                )
              ) AS a
              LEFT JOIN (
                SELECT
                  STATE AS STATE_NAME,
                  SAFE_DIVIDE(SAFE_DIVIDE(AEPS_GTV, 1e6), AEPS_MARKET_SIZE) AS SM_AEPS_MARKET_SHARE
                FROM (
                  SELECT
                    STATE AS STATE_NAME,
                    SUM(AEPS_GTV) AS AEPS_GTV,
                    SUM(AEPS_MARKET_SIZE) AS AEPS_MARKET_SIZE,
                    MAX(month) AS MONTH
                  FROM `spicemoney-dwh.analytics_dwh.sm_business_review_apr_2024`
                  GROUP BY state
                )
              ) AS b
              ON a.STATE_NAME = b.STATE_NAME
            )
            """
            df = client.query(q_aeps_change).result().to_dataframe()
            merged_gdf = gdf.merge(df, left_on="STATE_NAME", right_on="STATE_NAME", how="left")

        elif boundary == "district_level":
            q_aeps_change = f"""
            SELECT
              *,
              ROUND((input_month_ms - apr24_month_ms) * 100, 2) AS CHANGE_IN_AEPS_MARKET_SHARE
            FROM (
              SELECT
                a.DISTRICT_NAME,
                a.STATE AS STATE_x,
                a.SM_AEPS_MARKET_SHARE AS input_month_ms,
                b.SM_AEPS_MARKET_SHARE AS apr24_month_ms
              FROM {table_name} AS a
              LEFT JOIN `spicemoney-dwh.analytics_dwh.sm_business_review_apr_2024` AS b
              ON a.DISTRICT_NAME = b.DISTRICT_NAME
            )
            """
            df = client.query(q_aeps_change).result().to_dataframe()
            merged_gdf = gdf.merge(df, left_on="District", right_on="DISTRICT_NAME", how="left")

        else:
            raise ValueError("Invalid boundary for CHANGE_IN_AEPS_MARKET_SHARE")

    elif metric == "BL_DL_COUNT":
        # BL_DL_COUNT from Impact users
        if boundary == "state_level":
            q_sales = f"""
            SELECT
              state AS STATE_NAME,
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
            df = client.query(q_sales).result().to_dataframe()
            merged_gdf = gdf.merge(df, left_on="STATE_NAME", right_on="STATE_NAME", how="left")

        elif boundary == "district_level":
            q_sales = f"""
            SELECT
              a.district AS DISTRICT_NAME,
              a.state AS STATE_x,
              COALESCE(BL_DL_COUNT, 0) AS BL_DL_COUNT
            FROM (
              SELECT DISTINCT district, state
              FROM `spicemoney-dwh.analytics_dwh.v_pincode_master`
            ) AS a
            LEFT JOIN (
              SELECT
                district,
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
            df = client.query(q_sales).result().to_dataframe()
            merged_gdf = gdf.merge(df, left_on="District", right_on="DISTRICT_NAME", how="left")

        else:
            raise ValueError("Invalid boundary for BL_DL_COUNT")

    elif metric == "ACTIVE_PARTNERS":
        # ACTIVE_PARTNERS (default logic Feb 2025)
        print("Active Partners section")
        if boundary == "state_level":
            q_partners = f"""
            SELECT
              a.state AS STATE_NAME,
              COALESCE(ACTIVE_PARTNERS, 0) AS ACTIVE_PARTNERS
            FROM (
              SELECT DISTINCT district, state
              FROM `spicemoney-dwh.analytics_dwh.v_pincode_master`
            ) AS a
            LEFT JOIN (
              SELECT
                State,
                COUNT(DISTINCT distributor_id) AS ACTIVE_PARTNERS
              FROM (
                SELECT t1.distributor_id, t2.District, t2.State
                FROM (
                  SELECT
                    distributor_id,
                    District,
                    TOTAL_COMMISSION
                  FROM `spicemoney-dwh.analytics_dwh.monthly_distributor_commission`
                  WHERE month = '2025-02-01'
                    AND TOTAL_COMMISSION > 0
                ) AS t1
                LEFT JOIN (
                  SELECT
                    retailer_id AS distributor_id,
                    final_district AS District,
                    final_state AS State
                  FROM `spicemoney-dwh.analytics_dwh.v_client_pincode`
                  WHERE retailer_id IN (
                    SELECT DISTINCT md_code
                    FROM `spicemoney-dwh.prod_dwh.client_details`
                    WHERE client_type IN ('CME','distributor')
                  )
                ) AS t2
                ON t1.distributor_id = t2.distributor_id
              ) AS b
              GROUP BY State
            ) AS b
            ON a.state = b.State
            """
            df = client.query(q_partners).result().to_dataframe()
            merged_gdf = gdf.merge(df, left_on="STATE_NAME", right_on="STATE_NAME", how="left")

        elif boundary == "district_level":
            q_partners = f"""
            SELECT
              a.district AS DISTRICT_NAME,
              a.state AS STATE_x,
              COALESCE(ACTIVE_PARTNERS, 0) AS ACTIVE_PARTNERS
            FROM (
              SELECT DISTINCT district, state
              FROM `spicemoney-dwh.analytics_dwh.v_pincode_master`
            ) AS a
            LEFT JOIN (
              SELECT
                District,
                COUNT(DISTINCT distributor_id) AS ACTIVE_PARTNERS
              FROM (
                SELECT t1.distributor_id, t2.District, t2.State
                FROM (
                  SELECT
                    distributor_id,
                    District,
                    TOTAL_COMMISSION
                  FROM `spicemoney-dwh.analytics_dwh.monthly_distributor_commission`
                  WHERE month = '2025-02-01'
                    AND TOTAL_COMMISSION > 0
                ) AS t1
                LEFT JOIN (
                  SELECT
                    retailer_id AS distributor_id,
                    final_district AS District,
                    final_state AS State
                  FROM `spicemoney-dwh.analytics_dwh.v_client_pincode`
                  WHERE retailer_id IN (
                    SELECT DISTINCT md_code
                    FROM `spicemoney-dwh.prod_dwh.client_details`
                    WHERE client_type IN ('CME','distributor')
                  )
                ) AS t2
                ON t1.distributor_id = t2.distributor_id
              )
              GROUP BY District
            ) AS b
            ON a.district = b.District
            """
            df = client.query(q_partners).result().to_dataframe()
            merged_gdf = gdf.merge(df, left_on="District", right_on="DISTRICT_NAME", how="left")

        else:
            raise ValueError("Invalid boundary for ACTIVE_PARTNERS")

    else:
        # --------------------------------------------
        # Any other metric: use main business review tables
        # --------------------------------------------
        if boundary == "state_level":
            table_name = f"`spicemoney-dwh.analytics_dwh.sm_business_review_{month_str}`"

            q = f"""
            SELECT
              *,
              SAFE_DIVIDE(SAFE_DIVIDE(AEPS_GTV, 1e6), AEPS_MARKET_SIZE) AS SM_AEPS_MARKET_SHARE
            FROM (
              SELECT
                STATE AS STATE_NAME,
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
                SUM(CASA_transacting) AS CASA_TRANSACTING,
                SUM(CASA_SPLUS_ACCOUNTS_TRANSACTING) AS CASA_SPLUS_ACCOUNTS_TRANSACTING,
                SUM(TRANSACTING_SPs_non_CMS) AS TRANSACTING_SPs_non_CMS,
                SUM(THREE_MONTH_CONT_SP_non_CMS) AS THREE_MONTH_CONT_SP_non_CMS,
                SUM(AEPS_MARKET_SIZE) AS AEPS_MARKET_SIZE,
                SUM(CMS_MARKET_SIZE) AS CMS_MARKET_SIZE,
                SUM(SM_CMS_OPPORTUNITY_SHARE) AS SM_CMS_OPPORTUNITY_SHARE,
                SUM(GROSS_ADDS) AS GROSS_ADDS,
                SUM(NET_ADDS) AS NET_ADDS,
                SUM(SP_NEW_ACTIVATIONS_non_CMS) AS SP_NEW_ACTIVATIONS_non_CMS,
                SUM(SP_USAGE_CHURN_non_CMS) AS SP_USAGE_CHURN_non_CMS,
                SUM(SP_USAGE_CHURN_PERC_non_CMS) AS SP_USAGE_CHURN_PERC_non_CMS,
                SUM(VIP_PLAN_ACTIVE_SMAs) AS VIP_PLAN_ACTIVE_SMAs,
                SUM(PINCODES_WITH_0_5_SMA_density) AS PINCODES_WITH_0_5_SMA_density,
                SUM(TOTAL_PINCODES) AS TOTAL_PINCODES,
                SUM(BL_DL_COUNT) AS BL_DL_COUNT,
                SUM(PROMOTERS) AS PROMOTERS,
                SUM(ACTIVE_FSEs) AS ACTIVE_FSEs,
                SUM(ACTIVE_PARTNERS) AS ACTIVE_PARTNERS,
                SUM(ENGAGED_PARTNERS) AS ENGAGED_PARTNERS,
                SUM(POPULATION) AS POPULATION,
                SUM(TOTAL_GM) AS TOTAL_GM,
                MAX(month) AS MONTH
              FROM {table_name}
              GROUP BY state
            )
            """
            df = client.query(q).result().to_dataframe()
            merged_gdf = gdf.merge(df, left_on="STATE_NAME", right_on="STATE_NAME", how="left")

        elif boundary == "district_level":
            table_name = f"`spicemoney-dwh.analytics_dwh.sm_business_review_{month_str}`"
            q = f"SELECT * FROM {table_name}"
            df = client.query(q).result().to_dataframe()
            merged_gdf = gdf.merge(df, left_on="District", right_on="DISTRICT_NAME", how="left")

        else:
            raise ValueError("Invalid boundary type. Choose 'district_level' or 'state_level'.")

    # --------------------------------------------------------
    # Post-processing: ensure types, CRS, etc.
    # --------------------------------------------------------
    # Convert any datetime columns to string
    for col in merged_gdf.columns:
        if pd.api.types.is_datetime64_any_dtype(merged_gdf[col]):
            merged_gdf[col] = merged_gdf[col].astype(str)

    # Fix datetime index if needed
    if isinstance(merged_gdf.index, pd.DatetimeIndex):
        merged_gdf = merged_gdf.reset_index()

    # Ensure GeoDataFrame
    if not isinstance(merged_gdf, gpd.GeoDataFrame):
        merged_gdf = gpd.GeoDataFrame(merged_gdf)

    # Ensure CRS
    if merged_gdf.crs is None:
        merged_gdf.set_crs(epsg=4326, inplace=True)
    merged_gdf = merged_gdf.to_crs(epsg=4326)

    # --------------------------------------------------------
    # Metric bins & color selection
    # --------------------------------------------------------
    if boundary == "district_level":
        metric_list_to_be_used = predefined_metric_bins_district_level
        color_map_to_be_used = predefined_metric_colors_district_level
    else:
        metric_list_to_be_used = predefined_metric_bins_state_level
        color_map_to_be_used = predefined_metric_colors_state_level

    # CUTTING GDF based on State (from updated notebook)
    if geography == "State":
        merged_gdf = merged_gdf[merged_gdf["STATE_x"] == state]

    # Choose bins & colors
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
        color_map = color_map_to_be_used.get(metric, {})
    else:
        merged_gdf, color_map = get_valid_bins(merged_gdf, metric)

    # Drop MONTH for most metrics
    if metric not in (
        "DISTRIBUTOR_COMMISSION",
        "AVG_DISTR_COMMISSION",
        "CHANGE_IN_AEPS_MARKET_SHARE",
        "BL_DL_COUNT",
        "ACTIVE_PARTNERS",
    ):
        if "MONTH" in merged_gdf.columns:
            merged_gdf = merged_gdf.drop("MONTH", axis=1)

    # --------------------------------------------------------
    # Create Folium map
    # --------------------------------------------------------
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
        }

    if boundary == "state_level":
        tooltip = GeoJsonTooltip(
            fields=["STATE_NAME", metric, "Buckets"],
            aliases=["State:", metric, "Category:"],
            localize=True,
            sticky=False,
            labels=True,
            style="background-color: white; color: black; font-weight: bold;",
        )
    else:
        tooltip = GeoJsonTooltip(
            fields=["DISTRICT_NAME", metric, "Buckets"],
            aliases=["District:", metric, "Category:"],
            localize=True,
            sticky=False,
            labels=True,
            style="background-color: white; color: black; font-weight: bold;",
        )

    folium.GeoJson(
        merged_gdf,
        name=metric,
        style_function=style_function,
        tooltip=tooltip,
    ).add_to(folium_map)

    # --------------------------------------------------------
    # Annotations
    # --------------------------------------------------------
    if annotations == "YES":
        if boundary == "state_level":
            for _, row in merged_gdf.iterrows():
                centroid = row.geometry.centroid
                folium.Marker(
                    location=[centroid.y, centroid.x],
                    icon=folium.DivIcon(
                        html=(
                            '<div style="font-size:10px; font-weight:bold; color:black;">'
                            f'{row["STATE_NAME"]}</div>'
                        )
                    ),
                ).add_to(folium_map)
        else:
            for _, row in merged_gdf.iterrows():
                centroid = row.geometry.centroid
                folium.Marker(
                    location=[centroid.y, centroid.x],
                    icon=folium.DivIcon(
                        html=(
                            '<div style="font-size:10px; font-weight:bold; color:black;">'
                            f'{row["DISTRICT_NAME"]}</div>'
                        )
                    ),
                ).add_to(folium_map)

    # --------------------------------------------------------
    # Legend + Title + Save
    # --------------------------------------------------------
    folium_map = add_legend(folium_map, metric, color_map)
    map_title = f"{metric} Distribution - {geography} ({month_year})"
    folium_map = add_title(folium_map, map_title, metric, geography, month_year, state)

    if geography == "State":
        file_name = f"MAP_State_{state}_{boundary}_{metric}_{month_year}.html"
    else:
        file_name = f"MAP_National_{boundary}_{metric}_{month_year}.html"

    # folium_map.save(file_name)

    return folium_map, file_name


# ------------------------------------------------------------
# Streamlit UI
# ------------------------------------------------------------
def build_month_list():
    """Generate list of months from Jan 2024 to previous month."""
    today = date.today()
    start_year, start_month = 2024, 4  # as in notebook (from Apr 2024)
    current_year, current_month = today.year, today.month

    end_year = current_year
    end_month = current_month - 1 if current_month > 1 else 12
    if current_month == 1:
        end_year -= 1

    months = []
    year, month = start_year, start_month
    while (year < end_year) or (year == end_year and month <= end_month):
        months.append(date(year, month, 1).strftime("%Y-%m-%d"))
        if month == 12:
            month = 1
            year += 1
        else:
            month += 1
    return months





import streamlit as st
import streamlit.components.v1 as components

def main():
    header_container = st.container()
    map_placeholder = st.empty()  # you probably already have something like this

    st.set_page_config(
        page_title="District / State Map Generator",
        layout="wide",
    )

    # ---------- Header row: title (left) + download (right) ----------
    col1, col2 = st.columns([4, 1])

    with col1:
        st.title("🗺️ Automated District / State Map Generator")

    # with col2:
    #     map_ready = "map_file_bytes" in st.session_state

    #     if map_ready:
    #         clicked = st.download_button(
    #             label="⬇️ Download HTML Map",
    #             data=st.session_state["map_file_bytes"],
    #             file_name=st.session_state.get("map_file_name", "map.html"),
    #             mime="text/html",
    #             use_container_width=True,
    #             key="download_html_map",
    #         )
    #         if clicked:
    #             st.success("Map download started.")
    #     else:
    #         # Show disabled button in same place until a map is generated
    #         st.download_button(
    #             label="⬇️ Download HTML Map",
    #             data=b"",               # dummy
    #             file_name="map.html",   # dummy
    #             mime="text/html",
    #             disabled=True,
    #             use_container_width=True,
    #             key="download_html_map_disabled",
    #         )


    # This should be outside of `if generate_btn:`
    # and run on every script rerun

    # ---------- Layout: sidebar + main map area ----------
    with st.sidebar:
        st.header("Configuration")

        geography = st.selectbox("Select Geography", ["State", "National"])
        boundary = st.selectbox("Select Boundary", ["district_level", "state_level"])

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
                "AVG_DISTR_COMMISSION",
                "CHANGE_IN_AEPS_MARKET_SHARE",
                # ... any other metrics you already have
            ],
        )

        month_year = st.date_input(
            "Select Month-Year",
            format="YYYY-MM-DD",
        ).strftime("%Y-%m-%d")

        annotations = st.selectbox("Need Annotations?", ["YES", "NO"])

        # State selection only if Geography == State
        state = None
        if geography == "State":
            state = st.selectbox(
                "Select State",
                [
                    
                    "UTTAR PRADESH",
                    "BIHAR",
                    "RAJASTHAN",
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
                    "TAMIL NADU",
                ],
            )

        generate_btn = st.button("Generate Map")

    # Placeholder for spinner + map
    map_placeholder = st.empty()

    if generate_btn:
        with st.spinner("🔄 Generating map, please wait..."):
            # Optional: show a small info panel while generating
            st.info(
                f"Generating map for:\n\n"
                f"- Geography: {geography}\n"
                f"- Boundary: {boundary}\n"
                f"- Metric: {metric}\n"
                f"- Month-Year: {month_year}\n"
                f"- State: {state if state else 'N/A'}\n"
                f"- Annotations: {annotations}"
            )

            try:

                folium_map, file_name = generate_folium_map(
                geography, boundary, metric, month_year, annotations, state
                )

                # Show map in the container
                map_html = folium_map._repr_html_()
                with map_placeholder.container():
                    components.html(map_html, height=720, width=None)

                # 🔑 Store HTML in session_state for the download button
                full_html = folium_map.get_root().render()
                st.session_state["map_file_bytes"] = full_html.encode("utf-8")
                st.session_state["map_file_name"] = file_name
                st.session_state["map_file_name"] = file_name

                st.success(f"Map generated successfully (suggested file name: `{file_name}`).")


                with header_container:
                    # col1, col2 = st.columns([4, 1])

                    # with col1:
                    #     st.title("🗺️ Automated District / State Map Generator")

                    with col2:
                        map_ready = "map_file_bytes" in st.session_state

                        if map_ready:
                            clicked = st.download_button(
                                label="⬇️ Download HTML Map",
                                data=st.session_state["map_file_bytes"],
                                file_name=st.session_state.get("map_file_name", "map.html"),
                                mime="text/html",
                                use_container_width=True,
                                key="download_html_map",
                            )
                            if clicked:
                                st.success("Map download started.")
                        else:
                            st.download_button(
                                label="⬇️ Download HTML Map",
                                data=b"",              # dummy
                                file_name="map.html",  # dummy
                                mime="text/html",
                                disabled=True,
                                use_container_width=True,
                                key="download_html_map_disabled",
                            )
               


                # folium_map, file_name = generate_folium_map(
                #     geography, boundary, metric, month_year, annotations, state
                # )

                # # 1️⃣ Show map inline in the main area
                # map_html = folium_map._repr_html_()
                # with map_placeholder.container():
                #     components.html(map_html, height=720, width=None)

                # # 2️⃣ Prepare full HTML in memory for the download button
                # full_html = folium_map.get_root().render()
                # st.session_state["map_file_bytes"] = full_html.encode("utf-8")
                # st.session_state["map_file_name"] = file_name

                # # 3️⃣ Let the user know the map is ready (but NOT saved anywhere)
                # st.success(f"Map generated successfully (suggested file name: `{file_name}`).")

            except Exception as e:
                st.error(f"Error while generating map: {e}")


if __name__ == "__main__":
    main()


# def main():
#     st.set_page_config(
#         page_title="District / State Map Generator", layout="wide"
#     )

#     # --- Header row: title (left) + download button (right) ---
#     col1, col2 = st.columns([4, 1])

#     with col1:
#         st.title("🗺️ Automated District / State Map Generator")

#     with col2:
#         # Show active download button only after a map has been generated
#         if "map_file_bytes" in st.session_state:
#             st.download_button(
#                 label="⬇️ Download Map",
#                 data=st.session_state["map_file_bytes"],
#                 file_name=st.session_state.get("map_file_name", "map.html"),
#                 mime="text/html",
#                 use_container_width=True,
#             )
#         else:
#             # Disabled button placeholder so the user sees where download will appear
#             st.button(
#                 "⬇️ Download Map",
#                 disabled=True,
#                 use_container_width=True,
#             )


#     # ---------------- Sidebar configuration ----------------
#     st.sidebar.header("Configuration")

#     geography_options = ["State", "National"]
#     boundary_options = ["district_level", "state_level"]
#     metric_options = [
#         "TRANSACTING_SMAs",
#         "SM_AEPS_MARKET_SHARE",
#         "CHANGE_IN_AEPS_MARKET_SHARE",
#         "GROSS_ADDS",
#         "NET_ADDS",
#         "SP_WINBACK",
#         "SP_NEW_ACTIVATIONS_non_CMS",
#         "SP_USAGE_CHURN_non_CMS",
#         "SPs",
#         "BL_DL_COUNT",
#         "ACTIVE_PARTNERS",
#         "DISTRIBUTOR_COMMISSION",
#         "AVG_DISTR_COMMISSION",
#     ]
#     annotations_options = ["YES", "NO"]
#     state_options = [
#         "TAMIL NADU",
#         "UTTAR PRADESH",
#         "BIHAR",
#         "RAJASTHAN",
#         "WEST BENGAL",
#         "MADHYA PRADESH",
#         "MAHARASHTRA",
#         "KARNATAKA",
#         "ODISHA",
#         "CHATTISGARH",
#         "JHARKHAND",
#         "PUNJAB",
#         "DELHI_NCR",
#         "HARYANA",
#     ]

#     geography = st.sidebar.selectbox("Select Geography", geography_options)
#     boundary = st.sidebar.selectbox("Select Boundary", boundary_options)
#     metric = st.sidebar.selectbox("Select Metric", metric_options)

#     # Month list (first day of each month)
#     months = build_month_list()
#     month_year = st.sidebar.selectbox(
#         "Select Month-Year", months, index=len(months) - 1
#     )

#     annotations = st.sidebar.selectbox("Need Annotations?", annotations_options)

#     # State selector only when geography = "State"
#     if geography == "State":
#         state = st.sidebar.selectbox("Select State", state_options)
#     else:
#         state = "N/A"

#     st.sidebar.markdown("---")
#     generate_btn = st.sidebar.button("Generate Map")

#     # Placeholder for map & spinner
#     map_placeholder = st.empty()

#     if generate_btn:
#         info_text = (
#             f"Generating map for:\n"
#             f"- Geography: {geography}\n"
#             f"- Boundary: {boundary}\n"
#             f"- Metric: {metric}\n"
#             f"- Month-Year: {month_year}\n"
#             f"- State: {state}\n"
#             f"- Annotations: {annotations}"
#         )
#         st.info(info_text)

#         # Show custom circular loading spinner inside the map area
#         spinner_html = """
#         <div style="display:flex; flex-direction:column; align-items:center; justify-content:center; height:700px;">
#             <div class="loader"></div>
#             <div style="margin-top:20px; font-size:18px; font-weight:600;">
#                 Generating map, please wait...
#             </div>
#         </div>
#         <style>
#         .loader {
#           border: 16px solid #f3f3f3;
#           border-top: 16px solid #3498db;
#           border-radius: 50%;
#           width: 120px;
#           height: 120px;
#           animation: spin 1s linear infinite;
#         }
#         @keyframes spin {
#           0% { transform: rotate(0deg); }
#           100% { transform: rotate(360deg); }
#         }
#         </style>
#         """

#         with map_placeholder.container():
#             components.html(spinner_html, height=720)

#         try:
#             folium_map, file_name = generate_folium_map(
#                 geography, boundary, metric, month_year, annotations, state
#             )

#             # Replace spinner with map
#             map_html = folium_map._repr_html_()
#             with map_placeholder.container():
#                 components.html(map_html, height=720, width=None)

#             # --- Store file bytes for the top-right download button ---
#             try:
#                 with open(file_name, "rb") as f:
#                     st.session_state["map_file_bytes"] = f.read()
#                 st.session_state["map_file_name"] = file_name
#             except Exception as e:
#                 st.warning(f"Map generated, but could not prepare download file: {e}")

#             st.success(f"Map saved as `{file_name}` in the working directory.")


#         except Exception as e:
#             map_placeholder.empty()
#             st.error(f"Error while generating map: {e}")


# if __name__ == "__main__":
#     main()
