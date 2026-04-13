import streamlit as st
import pandas as pd
from geopy.distance import geodesic
import time
import folium
from streamlit_folium import st_folium

# --- CONFIGURATION ---
st.set_page_config(page_title="MASA | Dispatch Center", layout="wide", page_icon="🚁")

# --- DATA LOADING ---
@st.cache_data
def load_hubs():
    return pd.read_csv('data/unified_drone_network.csv')

@st.cache_data
def load_facilities():
    # Use the health facilities data from your EDA
    return pd.read_csv('data/ghana_health_facilities_clean.csv')

try:
    df_hubs = load_hubs()
    df_facilities = load_facilities()
except Exception as e:
    st.error("Data files missing. Please check your 'data' folder.")
    st.stop()

# --- SIDEBAR: MISSION CONTROL ---
st.sidebar.title("🎮 Mission Control")
st.sidebar.markdown("---")

# 1. FACILITY SELECTION
st.sidebar.subheader("Step 1: Destination")
selected_facility_name = st.sidebar.selectbox("Select Target Health Facility:", df_facilities['FacilityName'].unique())
facility_info = df_facilities[df_facilities['FacilityName'] == selected_facility_name].iloc[0]
dest_coords = (facility_info['Latitude'], facility_info['Longitude'])

# 2. CARGO SELECTION
st.sidebar.subheader("Step 2: Cargo")
cargo_type = st.sidebar.selectbox("Item Type:", ["Vaccines", "Blood Bags", "Emergency Meds"])
quantity = st.sidebar.number_input("Quantity:", min_value=1, value=1, step=1)

# Weight Logic (from your business report)
weight_map = {"Vaccines": 0.2, "Blood Bags": 0.5, "Emergency Meds": 0.3}
total_weight = quantity * weight_map[cargo_type]
st.sidebar.info(f"⚖️ Total Weight: {total_weight:.2f} kg")

# Drone Allocation Logic (Max 2kg per drone)
drones_needed = int(-(total_weight // -2.0)) # Ceiling division
st.sidebar.warning(f"🚀 Deployment: {drones_needed} Drone(s)")

# --- MAIN INTERFACE ---
st.title("🚁 MASA Logistics Dashboard")
st.write(f"**Targeting:** {selected_facility_name} | **Region:** {facility_info.get('Region', 'N/A')}")

col_map, col_stats = st.columns([2, 1])

# LOGIC: FIND BEST HUB
distances = df_hubs.apply(lambda row: geodesic(dest_coords, (row['Latitude'], row['Longitude'])).km, axis=1)
df_hubs['dist_to_target'] = distances
# Find hubs that can actually reach the target
reachable = df_hubs[df_hubs['dist_to_target'] <= df_hubs['Range_km']]

with col_stats:
    st.subheader("📡 Connection Status")
    if not reachable.empty:
        best_hub = reachable.sort_values('dist_to_target').iloc[0]
        st.success(f"**Best Hub Found:** {best_hub['Hub_ID']}")
        st.metric("Operator", best_hub['Operator'])
        st.metric("Flight Distance", f"{best_hub['dist_to_target']:.2f} km")
        st.metric("Estimated Flight Time", f"{int(best_hub['dist_to_target'] * 1.2)} min")
        
        # DISPATCH BUTTON
        if st.button("🚀 SUBMIT DISPATCH ORDER", use_container_width=True):
            with st.status("Initializing flight sequence...", expanded=True) as status:
                time.sleep(1)
                st.write(f"Calculating trajectory to {selected_facility_name}...")
                time.sleep(1)
                st.write(f"Assigning {drones_needed} drone(s) from {best_hub['Hub_ID']}...")
                time.sleep(1.5)
                status.update(label="MISSION DISPATCHED!", state="complete", expanded=False)
            st.balloons()
    else:
        st.error("❌ NO REACHABLE HUB FOUND FOR THIS LOCATION")
        best_hub = None

with col_map:
    # Visualization
    m = folium.Map(location=[facility_info['Latitude'], facility_info['Longitude']], zoom_start=9, tiles='CartoDB Positron')
    
    # Marker for Facility
    folium.Marker(dest_coords, popup=selected_facility_name, icon=folium.Icon(color='red', icon='h-square', prefix='fa')).add_to(m)
    
    # Marker for Hub & Line
    if best_hub is not None:
        hub_coords = (best_hub['Latitude'], best_hub['Longitude'])
        folium.Marker(hub_coords, popup=f"Origin: {best_hub['Hub_ID']}", icon=folium.Icon(color='black', icon='plane', prefix='fa')).add_to(m)
        folium.PolyLine([dest_coords, hub_coords], color="blue", weight=3, opacity=0.7, dash_array='10').add_to(m)
        
    st_folium(m, width=800, height=500)