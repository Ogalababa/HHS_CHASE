"""
Report generator for classified event logs.

This module generates reports from the three separate logs:
- bus_log: Bus state changes and SOC updates
- laadinfra_log: Charging infrastructure events and power monitoring
- planning_log: Task assignment and journey execution events
"""
from __future__ import annotations

from typing import Dict, Optional, List, Any, TYPE_CHECKING
from datetime import datetime
from pathlib import Path
import html
import json

if TYPE_CHECKING:
    from models.infrastructure import Location
    # ✅ Import from engines.transport_engine (adapter layer)
    from engines.transport_engine import TransportSimulationEngine
    # Backward compatibility alias
    SecondBasedSimulationEngine = TransportSimulationEngine

from .statistics_generator import analyze_planning_statistics, generate_statistics_section
from .bus_status_generator import generate_bus_status_section


def generate_combined_report_from_classified_logs(
    sim: "SecondBasedSimulationEngine",
    output_path: str,
    map_output_path: str,
    title: str = "Combined Simulation Report",
    locations: Optional[Dict[str, "Location"]] = None,
    config: Optional[Any] = None,
):
    """
    Generates a combined HTML report from classified event logs.
    
    Args:
        sim: The SecondBasedSimulationEngine object with classified logs
        output_path: Path for the main combined report
        map_output_path: Path where the map file will be saved
        title: Report title
        locations: Optional dictionary of Location objects
    """
    # Load classified logs
    bus_log = sim.classified_logger.bus_log
    laadinfra_log = sim.classified_logger.laadinfra_log
    planning_log = sim.classified_logger.planning_log
    
    print(f"\n--- Generating Combined Report from Classified Logs ---")
    print(f"Bus log events: {len(bus_log)}")
    print(f"LaadInfra log events: {len(laadinfra_log)}")
    print(f"Planning log events: {len(planning_log)}")
    
    # Generate replay map from classified logs (disabled - map replay removed from HTML report)
    # generate_replay_map_from_classified_logs(
    #     sim, map_output_path, locations=locations
    # )
    
    # Generate planning detailed report from planning_log
    planning_section = generate_planning_detailed_section(planning_log, sim.world)
    
    # Generate breakdown table body for the main table
    breakdown_table_body = generate_breakdown_table_body(planning_log, sim.world, laadinfra_log)
    
    # Extract optional hourly limits for Telexstraat (reporting only, not used in simulation)
    telexstraat_limits = None
    if config is not None:
        extra_params = getattr(config, "extra_report_params", None)
        if isinstance(extra_params, dict):
            telexstraat_limits = extra_params.get("telexstraat_hourly_limits_kw")

    # Generate laadinfra detailed report from laadinfra_log
    laadinfra_section = generate_laadinfra_detailed_section(
        laadinfra_log,
        locations or {},
        planning_log,
        telexstraat_hourly_limits_kw=telexstraat_limits,
    )
    
    # Generate summary
    summary_html = generate_summary_section(sim, planning_log, laadinfra_log)
    
    # Generate bus status section
    bus_status_html = generate_bus_status_section(sim, bus_log, planning_log, laadinfra_log)
    
    # Generate planning statistics (analyze blocks and journeys before simulation)
    # Note: This uses the world object which contains the original planning data
    if config is None:
        # Try to get config from sim if available
        config = getattr(sim, 'config', None)
    
    if config:
        # Pass bus_log, planning_log, and skipped blocks/journeys to analyze_planning_statistics
        statistics = analyze_planning_statistics(
            sim.world, 
            config, 
            bus_log=bus_log,
            skipped_blocks=sim.skipped_blocks,
            skipped_journeys=sim.skipped_journeys,
            planning_log=planning_log
        )
        statistics_html = generate_statistics_section(statistics)
    else:
        statistics_html = "<p>Statistics not available (config not provided)</p>"
    
    # Get simulation stop time
    sim_stop_time = datetime.fromtimestamp(sim.current_time).strftime('%Y-%m-%d %H:%M:%S') if sim.current_time else "N/A"
    
    # Load template
    template_path = Path(__file__).parent / "templates" / "combined_report.html"
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            template_html = f.read()
    except FileNotFoundError:
        print(f"[WARNING] Template combined_report.html not found.")
        return
    
    # Replace placeholders (using lowercase as in template)
    final_html = template_html.replace("{{ title }}", title)
    final_html = final_html.replace("{{ statistics_section }}", statistics_html)
    final_html = final_html.replace("{{ summary_section }}", summary_html)
    final_html = final_html.replace("{{ breakdown_table_body }}", breakdown_table_body)
    final_html = final_html.replace("{{ laadinfra_section }}", laadinfra_section)
    final_html = final_html.replace("{{ bus_status_section }}", bus_status_html)
    final_html = final_html.replace("{{ sim_stop_time }}", sim_stop_time)
    
    # Save report
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(final_html)
    
    print(f"Combined report generated: {output_path}")


def generate_summary_section(
    sim: "SecondBasedSimulationEngine",
    planning_log: List[Dict[str, Any]],
    laadinfra_log: List[Dict[str, Any]],
) -> str:
    """Generate summary section HTML."""
    completed_journeys = len(sim.completed_journeys)
    skipped_journeys = len(sim.skipped_journeys)
    skipped_blocks = len(sim.skipped_blocks)
    
    # Count total journeys from planning_log (journey_start events) or from world
    # This gives us the actual number of journeys that were attempted
    journey_start_events = [log for log in planning_log if log.get('event') == 'journey_start']
    if journey_start_events:
        total_journeys = len(journey_start_events)
    else:
        # Fallback: count from world.blocks if no journey_start events in log
        total_journeys = sum(len(block.journeys) for block in sim.world.blocks.values())
    
    # Count total blocks from planning_log (block_assigned events) or from world
    block_assigned_events = [log for log in planning_log if log.get('event') == 'block_assigned']
    if block_assigned_events:
        total_blocks = len(set(log.get('block_id') for log in block_assigned_events if log.get('block_id')))
    else:
        # Fallback: count from world.blocks if no block_assigned events in log
        total_blocks = len(sim.world.blocks)
    
    # Count completed blocks (blocks that have at least one completed journey)
    completed_blocks = 0
    for block in sim.world.blocks.values():
        # Check if any journey in this block was completed
        if any(journey in sim.completed_journeys for journey in block.journeys):
            completed_blocks += 1
    
    # Count unique buses
    bus_vins = set()
    for log in planning_log:
        if log.get('bus_vin'):
            bus_vins.add(log['bus_vin'])
    
    # Count charging sessions
    charging_sessions = len([log for log in laadinfra_log if log.get('event') == 'charging_started'])
    
    # Count total bus replacements
    total_bus_replacements = len([log for log in planning_log if log.get('event') == 'journey_replacement'])
    
    # Count block end return journeys (8xxxxxx)
    # These are journeys with id starting with 8 and 7 digits total, type BLOCK_END_RETURN_TO_TELEXSTRAAT
    block_end_return_journeys_count = 0
    
    # Check all journeys in world.blocks for 8xxxxxx journeys
    for block in sim.world.blocks.values():
        for journey in block.journeys:
            journey_id_str = str(journey.journey_id)
            # Extract original journey_id (remove date suffix if present)
            original_journey_id = journey_id_str
            if "_" in journey_id_str:
                parts = journey_id_str.rsplit("_", 1)
                if len(parts) == 2 and len(parts[1]) == 10:  # Date part is 10 chars (YYYY-MM-DD)
                    original_journey_id = parts[0]
            
            # Check if it's a block end return journey (8xxxxxx - 7 digits starting with 8)
            if (len(original_journey_id) == 7 and 
                original_journey_id[0] == '8' and 
                original_journey_id.isdigit() and
                journey.journey_type == "BLOCK_END_RETURN_TO_TELEXSTRAAT"):
                block_end_return_journeys_count += 1
    
    summary_html = f"""
    <div class="summary-section">
        <h2>Simulation Summary</h2>
        <p><strong>Simulation stopped at:</strong> {datetime.fromtimestamp(sim.current_time).strftime('%Y-%m-%d %H:%M:%S')}</p>
        <h3>Journeys</h3>
        <ul>
            <li><strong>Total Journeys:</strong> {total_journeys}</li>
            <li><strong>Completed Journeys:</strong> {completed_journeys}</li>
            <li><strong>Skipped Journeys:</strong> {skipped_journeys}</li>
            <li><strong>Other Journeys:</strong> {total_journeys - completed_journeys - skipped_journeys} (not started or in progress)</li>
        </ul>
        <p><em>Note: Skipped blocks and journeys are marked with ⚠️ SKIPPED in the Simulation Breakdown section below.</em></p>
        <h3>Blocks</h3>
        <ul>
            <li><strong>Total Blocks:</strong> {total_blocks}</li>
            <li><strong>Completed Blocks:</strong> {completed_blocks}</li>
            <li><strong>Skipped Blocks:</strong> {skipped_blocks}</li>
        </ul>
        <h3>Other Statistics</h3>
        <ul>
            <li><strong>Active Buses:</strong> {len(bus_vins)}</li>
            <li><strong>Charging Sessions:</strong> {charging_sessions}</li>
            <li><strong>Total Bus Replacements:</strong> {total_bus_replacements}</li>
            <li><strong>Block End Return Journeys:</strong> {block_end_return_journeys_count}</li>
        </ul>
    </div>
    """
    return summary_html


def generate_planning_detailed_section(
    planning_log: List[Dict[str, Any]],
    world: Any,
) -> str:
    """Generate planning detailed report section from planning_log."""
    # Group by block
    blocks_data = {}
    
    for log in planning_log:
        block_id = log.get('block_id')
        if not block_id:
            continue
        
        if block_id not in blocks_data:
            blocks_data[block_id] = {
                'journeys': {},
                'bus_number': log.get('bus_number'),
                'bus_vin': log.get('bus_vin')
            }
        
        journey_id = log.get('journey_id')
        if journey_id:
            if journey_id not in blocks_data[block_id]['journeys']:
                blocks_data[block_id]['journeys'][journey_id] = {
                    'points': []
                }
            
            if log.get('event') == 'point_arrival':
                blocks_data[block_id]['journeys'][journey_id]['points'].append({
                    'point_id': log.get('point_id'),
                    'point_name': log.get('point_name'),
                    'time': log.get('time'),
                    'soc_percent': log.get('soc_percent'),
                    'range_km': log.get('range_km')
                })
    
    # Generate HTML
    # Sort blocks by earliest point arrival time (earliest first)
    def get_block_earliest_time(block_data):
        """Get the earliest time from any point in any journey of the block."""
        earliest = None
        for journey_data in block_data['journeys'].values():
            for point in journey_data['points']:
                if point['time'] is not None:
                    if earliest is None or point['time'] < earliest:
                        earliest = point['time']
        return earliest if earliest is not None else float('inf')
    
    sorted_blocks = sorted(
        blocks_data.items(),
        key=lambda x: get_block_earliest_time(x[1])
    )
    
    html_parts = []
    assigned_bus_numbers = sorted(
        {
            str(data.get('bus_number'))
            for data in blocks_data.values()
            if data.get('bus_number') is not None
        },
        key=lambda x: int(x) if x.isdigit() else x,
    )

    filter_options_html = "\n".join(
        f'<option value="{html.escape(bus)}">{html.escape(bus)}</option>'
        for bus in assigned_bus_numbers
    )
    html_parts.append(f"""
    <div class="planning-filter-panel" style="margin: 10px 0 14px 0; padding: 10px; border: 1px solid #ddd; border-radius: 8px; background: #f8f9fa;">
        <div style="font-weight: 600; margin-bottom: 8px;">Assigned Bus Nr Filter (multi-select)</div>
        <div style="display: flex; gap: 10px; align-items: flex-start; flex-wrap: wrap;">
            <select id="planning-assigned-bus-filter" multiple size="6" style="min-width: 180px;">
                {filter_options_html}
            </select>
            <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                <button type="button" onclick="applyPlanningAssignedBusFilter()">Apply Filter</button>
                <button type="button" onclick="clearPlanningAssignedBusFilter()">Clear Filter</button>
                <button type="button" onclick="selectAllPlanningAssignedBusFilter()">Select All</button>
            </div>
        </div>
        <div id="planning-assigned-bus-filter-status" style="margin-top: 8px; color: #555;">
            Showing all blocks ({len(sorted_blocks)} total)
        </div>
    </div>
    """)
    for block_id, block_data in sorted_blocks:
        block = world.blocks.get(block_id) if world else None
        block_id_safe = block_id.replace(':', '-').replace('/', '-')
        
        assigned_bus = block_data.get('bus_number')
        assigned_bus_attr = html.escape(str(assigned_bus)) if assigned_bus is not None else "N/A"
        html_parts.append(f"""
        <div class="block-section" data-assigned-bus="{assigned_bus_attr}">
            <div class="block-header collapsed" id="block-header-{block_id_safe}" onclick="toggleBlock('{block_id_safe}')">
                <span class="toggle-icon">▶</span>
                <strong>Block: {block_id}</strong>
                <span>Bus: {block_data['bus_number']}</span>
            </div>
            <div class="block-content hidden" id="block-content-{block_id_safe}">
                <table>
                    <thead>
                        <tr>
                            <th>Journey ID</th>
                            <th>Point</th>
                            <th>Time</th>
                            <th>SOC (%)</th>
                            <th>Range (km)</th>
                        </tr>
                    </thead>
                    <tbody>
        """)
        
        # Sort journeys by earliest point time (earliest first)
        def get_journey_earliest_time(journey_data):
            """Get the earliest time from any point in the journey."""
            if not journey_data['points']:
                return float('inf')
            times = [p['time'] for p in journey_data['points'] if p['time'] is not None]
            return min(times) if times else float('inf')
        
        sorted_journeys = sorted(
            block_data['journeys'].items(),
            key=lambda x: get_journey_earliest_time(x[1])
        )
        
        for journey_id, journey_data in sorted_journeys:
            # Sort points by time (earliest first)
            sorted_points = sorted(
                journey_data['points'],
                key=lambda p: p['time'] if p['time'] is not None else float('inf')
            )
            
            for point in sorted_points:
                time_str = datetime.fromtimestamp(point['time']).strftime('%Y-%m-%d %H:%M:%S') if point['time'] else "N/A"
                # Format SOC safely (handle None values)
                soc_value = point.get('soc_percent')
                soc_str = f"{soc_value:.2f}" if soc_value is not None and isinstance(soc_value, (int, float)) else "-"
                # Format range_km safely (handle None values)
                range_value = point.get('range_km')
                range_str = f"{range_value:.2f}" if range_value is not None and isinstance(range_value, (int, float)) else "-"
                html_parts.append(f"""
                        <tr>
                            <td>{journey_id}</td>
                            <td>{point['point_name']} ({point['point_id']})</td>
                            <td>{time_str}</td>
                            <td>{soc_str}</td>
                            <td>{range_str}</td>
                        </tr>
                """)
        
        html_parts.append("""
                    </tbody>
                </table>
            </div>
        </div>
        """)
    
    html_parts.append("""
    <script>
    (function () {
        function selectedBusValues() {
            var select = document.getElementById('planning-assigned-bus-filter');
            if (!select) return [];
            var selected = [];
            for (var i = 0; i < select.options.length; i += 1) {
                if (select.options[i].selected) selected.push(select.options[i].value);
            }
            return selected;
        }

        function updateFilterStatus(visibleCount, totalCount, selected) {
            var statusEl = document.getElementById('planning-assigned-bus-filter-status');
            if (!statusEl) return;
            if (!selected.length) {
                statusEl.textContent = "Showing all blocks (" + totalCount + " total)";
                return;
            }
            statusEl.textContent =
                "Showing " + visibleCount + " / " + totalCount + " blocks for bus: " + selected.join(", ");
        }

        window.applyPlanningAssignedBusFilter = function () {
            var selected = selectedBusValues();
            var sections = document.querySelectorAll('.block-section[data-assigned-bus]');
            var total = sections.length;
            var visible = 0;
            for (var i = 0; i < sections.length; i += 1) {
                var section = sections[i];
                var bus = section.getAttribute('data-assigned-bus');
                var show = selected.length === 0 || selected.indexOf(bus) >= 0;
                section.style.display = show ? '' : 'none';
                if (show) visible += 1;
            }
            updateFilterStatus(visible, total, selected);
        };

        window.clearPlanningAssignedBusFilter = function () {
            var select = document.getElementById('planning-assigned-bus-filter');
            if (select) {
                for (var i = 0; i < select.options.length; i += 1) {
                    select.options[i].selected = false;
                }
            }
            window.applyPlanningAssignedBusFilter();
        };

        window.selectAllPlanningAssignedBusFilter = function () {
            var select = document.getElementById('planning-assigned-bus-filter');
            if (select) {
                for (var i = 0; i < select.options.length; i += 1) {
                    select.options[i].selected = true;
                }
            }
            window.applyPlanningAssignedBusFilter();
        };
    })();
    </script>
    """)

    return "\n".join(html_parts)


def generate_breakdown_table_body(
    planning_log: List[Dict[str, Any]],
    world: Any,
    laadinfra_log: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Generate breakdown table body HTML for the main simulation breakdown table."""
    # Build charging information map: (bus_vin, time) -> charging_info
    # Format: {bus_vin: {time: {'location_id': ..., 'charger_id': ..., 'connector_id': ..., 'requested_only': bool}}}
    charging_info_map = {}
    charging_requested_map = {}  # Track charging_requested events separately
    
    # Build skipped blocks map: block_id -> skipped_info
    skipped_blocks_map = {}
    for log in planning_log:
        if log.get('event') == 'block_skipped':
            block_id = log.get('block_id')
            if block_id:
                skipped_blocks_map[block_id] = {
                    'time': log.get('time'),
                    'reason': log.get('reason', 'Unknown reason'),
                    'bus_number': log.get('bus_number'),
                    'bus_vin': log.get('bus_vin')
                }
    
    # Build skipped journeys map: (block_id, journey_id) -> skipped_info
    skipped_journeys_map = {}
    for log in planning_log:
        if log.get('event') == 'journey_skipped_low_soc':
            block_id = log.get('block_id')
            journey_id = log.get('journey_id')
            if block_id and journey_id:
                skipped_journeys_map[(block_id, journey_id)] = {
                    'time': log.get('time'),
                    'soc_percent': log.get('soc_percent'),
                    'reason': log.get('reason', 'Low SOC'),
                    'bus_number': log.get('bus_number'),
                    'bus_vin': log.get('bus_vin')
                }
    
    # Build journey replacement map: (block_id, journey_id) -> replacement_info
    # This tracks which bus actually executed the journey after replacement
    journey_replacement_map = {}
    # Build return journey map: (block_id, return_journey_id) -> return_journey_info
    # This tracks return journeys and their original bus
    return_journey_map = {}
    # Build block end return journey map: (block_id, return_journey_id) -> block_end_return_journey_info
    block_end_return_journey_map = {}
    assignment_explain_map = {}
    import re
    for log in planning_log:
        if log.get('event') == 'block_end_return_journey_created':
            # Track block end return journeys and their bus
            block_id = log.get('block_id')
            return_journey_id = log.get('return_journey_id')
            if block_id and return_journey_id:
                block_end_return_journey_map[(block_id, return_journey_id)] = {
                    'bus_number': log.get('bus_number'),
                    'bus_vin': log.get('bus_vin'),
                    'time': log.get('time'),
                    'reason': log.get('reason', 'Block end return journey created')
                }
        elif log.get('event') == 'journey_replacement':
            block_id = log.get('block_id')
            journey_id = log.get('journey_id')
            if block_id and journey_id:
                # Try to get original_bus_number from different fields
                original_bus_number = log.get('bus_number')
                # If original_bus_number is None, try to extract from reason field
                if original_bus_number is None:
                    reason = log.get('reason', '')
                    # Reason format: "Bus 1403 cannot complete journey..."
                    match = re.search(r'Bus\s+(\d+)', reason)
                    if match:
                        original_bus_number = int(match.group(1))
                
                journey_replacement_map[(block_id, journey_id)] = {
                    'replacement_bus_number': log.get('replacement_bus_number'),
                    'replacement_bus_vin': log.get('replacement_bus_vin'),
                    'original_bus_number': original_bus_number,
                    'original_bus_vin': log.get('bus_vin'),
                    'time': log.get('time'),
                    'reason': log.get('reason', 'Journey replacement')
                }
        elif log.get('event') == 'return_journey_created':
            # Track return journeys and their original bus
            block_id = log.get('block_id')
            return_journey_id = log.get('return_journey_id')
            if block_id and return_journey_id:
                return_journey_map[(block_id, return_journey_id)] = {
                    'bus_number': log.get('bus_number'),
                    'bus_vin': log.get('bus_vin'),
                    'original_journey_id': log.get('original_journey_id'),
                    'time': log.get('time'),
                    'reason': log.get('reason', 'Return journey created')
                }
        elif log.get('event') == 'strategy_block_assignment_explain':
            block_id = log.get('block_id')
            if block_id:
                assignment_explain_map[block_id] = {
                    'time': log.get('time'),
                    'strategy': log.get('strategy'),
                    'assignment_mode': log.get('assignment_mode'),
                    'selected_bus_number': log.get('selected_bus_number'),
                    'selected_bus_point_id': log.get('selected_bus_point_id'),
                    'selected_bus_soc_percent': log.get('selected_bus_soc_percent'),
                    'origin_point_id': log.get('origin_point_id'),
                    'target_distance_km': log.get('target_distance_km'),
                    'changed_assignment': log.get('changed_assignment'),
                    'candidates': log.get('candidates', []),
                }
    
    # Build charging sessions map: {bus_vin: {start_time: {end_time, end_soc, location_id, charger_id, connector_id}}}
    # This tracks complete charging sessions with start and end times
    charging_sessions_map = {}
    if laadinfra_log:
        active_charging_sessions = {}  # {bus_vin: {start_time, location_id, charger_id, connector_id, start_soc, last_progress_time, current_soc}}
        for log in laadinfra_log:
            event_type = log.get('event')
            bus_vin = log.get('bus_vin')
            if not bus_vin:
                continue
                
            if event_type == 'charging_started':
                # Close existing session if any
                if bus_vin in active_charging_sessions:
                    old_session = active_charging_sessions[bus_vin]
                    if bus_vin not in charging_sessions_map:
                        charging_sessions_map[bus_vin] = {}
                    charging_sessions_map[bus_vin][old_session['start_time']] = {
                        'end_time': old_session.get('last_progress_time', old_session['start_time']),
                        'end_soc': old_session.get('current_soc', old_session['start_soc']),
                        'location_id': old_session['location_id'],
                        'charger_id': old_session['charger_id'],
                        'connector_id': old_session['connector_id']
                    }
                
                # Start new session
                active_charging_sessions[bus_vin] = {
                    'start_time': log.get('time'),
                    'location_id': log.get('location_id', 'N/A'),
                    'charger_id': log.get('charger_id', 'N/A'),
                    'connector_id': log.get('connector_id', 'N/A'),
                    'start_soc': log.get('soc_percent', 0.0),
                    'current_soc': log.get('soc_percent', 0.0),
                    'last_progress_time': log.get('time')
                }
            elif event_type == 'charging_progress' and bus_vin in active_charging_sessions:
                # Update session progress
                active_charging_sessions[bus_vin]['current_soc'] = log.get('soc_percent', active_charging_sessions[bus_vin]['current_soc'])
                active_charging_sessions[bus_vin]['last_progress_time'] = log.get('time')
            elif event_type == 'charging_stopped' and bus_vin in active_charging_sessions:
                # Close session
                session = active_charging_sessions[bus_vin]
                end_soc = log.get('soc_percent')
                if end_soc is None:
                    end_soc = session.get('current_soc', session['start_soc'])
                if bus_vin not in charging_sessions_map:
                    charging_sessions_map[bus_vin] = {}
                charging_sessions_map[bus_vin][session['start_time']] = {
                    'end_time': log.get('time'),
                    'end_soc': end_soc,
                    'location_id': session['location_id'],
                    'charger_id': session['charger_id'],
                    'connector_id': session['connector_id']
                }
                del active_charging_sessions[bus_vin]
        
        # Close remaining active sessions
        for bus_vin, session in active_charging_sessions.items():
            if bus_vin not in charging_sessions_map:
                charging_sessions_map[bus_vin] = {}
            charging_sessions_map[bus_vin][session['start_time']] = {
                'end_time': session.get('last_progress_time', session['start_time']),
                'end_soc': session.get('current_soc', session['start_soc']),
                'location_id': session['location_id'],
                'charger_id': session['charger_id'],
                'connector_id': session['connector_id']
            }
        
        # #region agent log
        # Debug: Log charging_sessions_map statistics, especially for Telexstraat
        try:
            debug_log_path = ".cursor/debug.log"
            telexstraat_sessions = 0
            total_sessions = 0
            for bus_vin, sessions in charging_sessions_map.items():
                for start_time, session in sessions.items():
                    total_sessions += 1
                    location_id = session.get('location_id', 'N/A')
                    if location_id == 'Telexstraat' or (isinstance(location_id, str) and 'Telexstraat' in location_id):
                        telexstraat_sessions += 1
            
            with open(debug_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "sessionId": "debug-session",
                    "runId": "report-gen",
                    "hypothesisId": "H4",
                    "location": "classified_report_generator.py:507",
                    "message": "Charging_sessions_map statistics",
                    "data": {
                        "total_sessions": total_sessions,
                        "telexstraat_sessions": telexstraat_sessions,
                        "unique_buses": len(charging_sessions_map)
                    },
                    "timestamp": datetime.now().timestamp() * 1000
                }) + "\n")
        except Exception as e:
            pass
        # #endregion
    
    # First, add charging_started events from laadinfra_log (most accurate)
    # #region agent log
    charging_started_events = []
    # #endregion
    if laadinfra_log:
        for log in laadinfra_log:
            if log.get('event') == 'charging_started':
                bus_vin = log.get('bus_vin')
                if bus_vin:
                    if bus_vin not in charging_info_map:
                        charging_info_map[bus_vin] = {}
                    charge_time = log.get('time')
                    location_id = log.get('location_id', 'N/A')
                    charger_id = log.get('charger_id', 'N/A')
                    connector_id = log.get('connector_id', 'N/A')
                    charging_info_map[bus_vin][charge_time] = {
                        'location_id': location_id,
                        'charger_id': charger_id,
                        'connector_id': connector_id,
                        'requested_only': False  # This is a started event
                    }
                    # #region agent log
                    charging_started_events.append({
                        'bus_vin': bus_vin,
                        'time': charge_time,
                        'location_id': location_id,
                        'charger_id': charger_id,
                        'connector_id': connector_id
                    })
                    # #endregion
    
    # #region agent log
    # Debug: Log charging_started events added to charging_info_map, especially Telexstraat
    try:
        debug_log_path = ".cursor/debug.log"
        telexstraat_events = [e for e in charging_started_events if e['location_id'] == 'Telexstraat' or (isinstance(e['location_id'], str) and 'Telexstraat' in e['location_id'])]
        with open(debug_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "sessionId": "debug-session",
                "runId": "report-gen",
                "hypothesisId": "H4",
                "location": "classified_report_generator.py:570",
                "message": "Charging_started events added to charging_info_map",
                "data": {
                    "total_events": len(charging_started_events),
                    "telexstraat_events": len(telexstraat_events),
                    "unique_buses": len(set(e['bus_vin'] for e in charging_started_events)),
                    "unique_locations": len(set(e['location_id'] for e in charging_started_events if e['location_id'] != 'N/A')),
                    "telexstraat_sample": telexstraat_events[:5] if telexstraat_events else []
                },
                "timestamp": datetime.now().timestamp() * 1000
            }) + "\n")
    except Exception as e:
        pass
    # #endregion
    
    # Also track charging_requested events separately (for showing "Charger unavailable" when requested but not started)
    for log in planning_log:
        if log.get('event') == 'charging_requested':
            bus_vin = log.get('bus_vin')
            location_id = log.get('location_id')
            if bus_vin and location_id:
                if bus_vin not in charging_requested_map:
                    charging_requested_map[bus_vin] = {}
                charge_time = log.get('time')
                if charge_time:
                    charging_requested_map[bus_vin][charge_time] = {
                        'location_id': location_id,
                        'journey_id': log.get('journey_id'),
                        'point_id': log.get('point_id')
                    }
                    
                    # Try to find a charging_started event that matches this charging_requested event
                    matched = False
                    best_match = None
                    best_time_diff = float('inf')
                    
                    if laadinfra_log:
                        for laad_log in laadinfra_log:
                            if (laad_log.get('event') == 'charging_started' and
                                laad_log.get('bus_vin') == bus_vin and
                                laad_log.get('location_id') == location_id):
                                started_time = laad_log.get('time')
                                if started_time:
                                    # Allow matching if charging_started is within 30 minutes before or 2 hours after charging_requested
                                    time_diff = started_time - charge_time
                                    if -1800 <= time_diff <= 7200:  # -30 min to +2 hours
                                        # Prefer the closest match in time
                                        if abs(time_diff) < abs(best_time_diff):
                                            best_match = laad_log
                                            best_time_diff = time_diff
                                            matched = True
                    
                    # If match found, use the charging_started info (already in charging_info_map)
                    # If no match found, we'll use charging_requested_map later to show "Charger unavailable"
    
    # Group by block
    blocks_data = {}
    
    for log in planning_log:
        block_id = log.get('block_id')
        if not block_id:
            continue
        
        if block_id not in blocks_data:
            blocks_data[block_id] = {
                'journeys': {},
                'bus_number': log.get('bus_number'),
                'bus_vin': log.get('bus_vin'),
                'block_start_time': None,
                'block_end_time': None,
                'skipped': False,
                'skip_info': None
            }
        
        # Check if this block was skipped (from block_skipped event)
        # BUT: Only mark as skipped if there's no block_assigned event (block was never successfully assigned)
        if block_id in skipped_blocks_map:
            # Don't mark as skipped yet - we'll check later if block was actually assigned
            pass
        
        # If block_assigned event exists, clear any skipped status
        event_type = log.get('event')
        if event_type == 'block_assigned':
            # Block was successfully assigned, so it's not skipped
            blocks_data[block_id]['skipped'] = False
            blocks_data[block_id]['skip_info'] = None
            # Update bus info from block_assigned event
            blocks_data[block_id]['bus_number'] = log.get('bus_number')
            blocks_data[block_id]['bus_vin'] = log.get('bus_vin')
        
        journey_id = log.get('journey_id')
        if journey_id:
            if journey_id not in blocks_data[block_id]['journeys']:
                blocks_data[block_id]['journeys'][journey_id] = {
                    'points': [],
                    'journey_start_time': None,
                    'journey_end_time': None
                }
            
            if event_type == 'journey_start':
                blocks_data[block_id]['journeys'][journey_id]['journey_start_time'] = log.get('time')
                if blocks_data[block_id]['block_start_time'] is None:
                    blocks_data[block_id]['block_start_time'] = log.get('time')
                # Store bus info from journey_start (this is the actual bus that started the journey)
                # If there was a replacement, this will be the replacement bus (from rescheduled journey_start event)
                blocks_data[block_id]['journeys'][journey_id]['bus_number'] = log.get('bus_number')
                blocks_data[block_id]['journeys'][journey_id]['bus_vin'] = log.get('bus_vin')
            elif event_type == 'journey_end':
                blocks_data[block_id]['journeys'][journey_id]['journey_end_time'] = log.get('time')
                blocks_data[block_id]['block_end_time'] = log.get('time')
            elif event_type in {'journey_skipped_low_soc', 'journey_skipped'}:
                # Mark journey as skipped
                blocks_data[block_id]['journeys'][journey_id]['skipped'] = True
                blocks_data[block_id]['journeys'][journey_id]['skip_time'] = log.get('time')
                blocks_data[block_id]['journeys'][journey_id]['skip_soc'] = log.get('soc_percent')
                blocks_data[block_id]['journeys'][journey_id]['skip_reason'] = log.get('reason', 'Low SOC')
            elif event_type == 'point_arrival':
                # Check if this point already exists (avoid duplicates)
                point_id = log.get('point_id')
                point_time = log.get('time')
                
                # Check if this point already exists in the list
                point_exists = False
                for existing_point in blocks_data[block_id]['journeys'][journey_id]['points']:
                    if existing_point.get('point_id') == point_id and existing_point.get('time') == point_time:
                        point_exists = True
                        break
                
                # Only add if it doesn't exist
                if not point_exists:
                    blocks_data[block_id]['journeys'][journey_id]['points'].append({
                        'point_id': point_id,
                        'point_name': log.get('point_name'),
                        'time': point_time,
                        'soc_percent': log.get('soc_percent'),
                        'range_km': log.get('range_km'),
                        'distance_to_next_m': None  # Will be filled from world if available
                    })
    
    # IMPORTANT: Ensure all journeys from world.blocks are included in blocks_data
    # This ensures that skipped journeys are also displayed in the report
    if world:
        for block_id, block in world.blocks.items():
            # Initialize block_data if it doesn't exist
            if block_id not in blocks_data:
                blocks_data[block_id] = {
                    'journeys': {},
                    'bus_number': None,
                    'bus_vin': None,
                    'block_start_time': None,
                    'block_end_time': None,
                    'skipped': False,
                    'skip_info': None
                }
            
            # Add all journeys from world.blocks (even if they were skipped)
            for journey in block.journeys:
                journey_id = journey.journey_id
                # Initialize journey_data if it doesn't exist
                if journey_id not in blocks_data[block_id]['journeys']:
                    blocks_data[block_id]['journeys'][journey_id] = {
                        'points': [],
                        'journey_start_time': journey.first_departure_datetime.timestamp() if journey.first_departure_datetime else None,
                        'journey_end_time': None,
                        'skipped': False,
                        'skip_time': None,
                        'skip_soc': None,
                        'skip_reason': None
                    }
                    
                    # Set block start time from first journey
                    if blocks_data[block_id]['block_start_time'] is None and journey.first_departure_datetime:
                        blocks_data[block_id]['block_start_time'] = journey.first_departure_datetime.timestamp()
                    
                    # Set block end time from last journey's last point
                    if journey.points:
                        last_point = journey.points[-1]
                        if last_point.arrival_datetime:
                            blocks_data[block_id]['block_end_time'] = last_point.arrival_datetime.timestamp()
                
                # Add points from world (only if not already added from planning_log)
                for point in journey.points:
                    point_time = point.arrival_datetime.timestamp() if point.arrival_datetime else None
                    # Check if point already exists
                    point_exists = False
                    for existing_point in blocks_data[block_id]['journeys'][journey_id]['points']:
                        if existing_point.get('point_id') == point.point_id and existing_point.get('time') == point_time:
                            point_exists = True
                            # Update distance if available
                            if point.distance_to_next_m and not existing_point.get('distance_to_next_m'):
                                existing_point['distance_to_next_m'] = point.distance_to_next_m
                            break
                    
                    if not point_exists:
                        blocks_data[block_id]['journeys'][journey_id]['points'].append({
                            'point_id': point.point_id,
                            'point_name': point.name,
                            'time': point_time,
                            'soc_percent': None,  # Will be filled from planning_log if available
                            'range_km': None,
                            'distance_to_next_m': point.distance_to_next_m
                        })
    
    # Normalize block time window from journey windows.
    # Rationale: event processing order can contain late updates and overwrite
    # block-level times. Canonical block boundaries are earliest journey start
    # and latest journey end inside the same block.
    for _block_id, block_data in blocks_data.items():
        journey_starts: list[float] = []
        journey_ends: list[float] = []
        for _journey_id, journey_data in block_data['journeys'].items():
            start_time = journey_data.get('journey_start_time')
            end_time = journey_data.get('journey_end_time')
            if start_time is not None:
                journey_starts.append(start_time)
            if end_time is not None:
                journey_ends.append(end_time)
        if journey_starts:
            block_data['block_start_time'] = min(journey_starts)
        if journey_ends:
            block_data['block_end_time'] = max(journey_ends)

    # Sort blocks by start time (earliest first)
    sorted_blocks = sorted(
        blocks_data.items(),
        key=lambda x: x[1]['block_start_time'] if x[1]['block_start_time'] is not None else float('inf')
    )
    
    html_rows = []
    for block_id, block_data in sorted_blocks:
        block = world.blocks.get(block_id) if world else None
        
        # Calculate block total distance
        block_distance = 0.0
        if block:
            for journey in block.journeys:
                for point in journey.points:
                    if point.distance_to_next_m:
                        block_distance += point.distance_to_next_m / 1000.0
        
        block_id_safe = block_id.replace(':', '-').replace('/', '-').replace(' ', '-')
        block_start_str = datetime.fromtimestamp(block_data['block_start_time']).strftime('%Y-%m-%d %H:%M:%S') if block_data['block_start_time'] else "N/A"
        block_end_str = datetime.fromtimestamp(block_data['block_end_time']).strftime('%Y-%m-%d %H:%M:%S') if block_data['block_end_time'] else "N/A"
        
        # IMPORTANT: Ensure all journeys from block are included, even if they don't have events
        # This ensures skipped journeys are displayed
        if block:
            for journey in block.journeys:
                journey_id = journey.journey_id
                if journey_id not in block_data['journeys']:
                    # Journey exists in block but has no events - likely skipped
                    block_data['journeys'][journey_id] = {
                        'points': [],
                        'journey_start_time': journey.first_departure_datetime.timestamp() if journey.first_departure_datetime else None,
                        'journey_end_time': None,
                        'skipped': True,  # Mark as skipped if no events
                        'skip_time': journey.first_departure_datetime.timestamp() if journey.first_departure_datetime else None,
                        'skip_soc': None,
                        'skip_reason': 'No events recorded - journey may have been skipped'
                    }
        
        # Journey and point rows (nested under block)
        # Sort journeys by start time (earliest first)
        def _journey_start_sort_key(item: tuple[str, Dict[str, Any]]) -> float:
            jid, jdata = item
            if jdata.get('journey_start_time') is not None:
                return float(jdata['journey_start_time'])
            if block:
                j_obj = next((j for j in block.journeys if j.journey_id == jid), None)
                if j_obj and j_obj.first_departure_datetime:
                    return float(j_obj.first_departure_datetime.timestamp())
            return float('inf')

        sorted_journeys = sorted(
            block_data['journeys'].items(),
            key=_journey_start_sort_key,
        )
        # If a journey is skipped due to low SOC during execution, downstream
        # journeys in the same block that never started should be marked skipped
        # (not "not started"), because the block was interrupted.
        downstream_interrupted = False
        for _jid, jdata in sorted_journeys:
            if jdata.get('skipped'):
                downstream_interrupted = True
                continue
            if (
                downstream_interrupted
                and jdata.get('journey_start_time') is None
                and not jdata.get('points')
            ):
                jdata['skipped'] = True
                jdata['skip_reason'] = 'Low SOC interruption in previous journey'
                jdata['skip_time'] = None
        
        # Find the first SOC in the block (from the first point of the first journey)
        # This represents "SOC at Arrival" - the SOC when the block starts
        block_first_soc = None
        for journey_id, journey_data in sorted_journeys:
            if journey_data['points']:
                # Get the first point (by time) in this journey
                sorted_points = sorted(
                    journey_data['points'],
                    key=lambda p: p['time'] if p['time'] is not None else float('inf')
                )
                if sorted_points:
                    first_point = sorted_points[0]
                    if first_point.get('soc_percent') is not None:
                        block_first_soc = first_point.get('soc_percent')
                        break  # Use the first journey's first point SOC
        
        # If no SOC found from points, try to get it from block_assigned event
        if block_first_soc is None:
            # Try to find block_assigned event for this block
            for log in planning_log:
                if (log.get('block_id') == block_id and 
                    log.get('event') == 'block_assigned' and
                    log.get('soc_percent') is not None):
                    block_first_soc = log.get('soc_percent')
                    break
        
        block_soc_str = f"{block_first_soc:.2f}" if block_first_soc is not None else "-"
        
        # Find charging info for the block (any charging during the block time range OR after block end)
        block_charging_info = "-"
        bus_vin = block_data.get('bus_vin')
        # #region agent log
        block_charging_matched = False
        block_charging_debug_info = {
            'block_id': block_id,
            'bus_vin': bus_vin,
            'has_charging_info_map': bus_vin in charging_info_map if bus_vin else False,
            'has_charging_sessions_map': bus_vin in charging_sessions_map if bus_vin else False,
            'charging_info_map_count': len(charging_info_map.get(bus_vin, {})) if bus_vin and bus_vin in charging_info_map else 0,
            'charging_sessions_map_count': len(charging_sessions_map.get(bus_vin, {})) if bus_vin and bus_vin in charging_sessions_map else 0
        }
        # #endregion
        if bus_vin and bus_vin in charging_info_map:
            # Find charging sessions that overlap with block time range OR after block end (within 2 hours)
            block_start = block_data.get('block_start_time')
            block_end = block_data.get('block_end_time')
            if block_start and block_end:
                # Extended time window: include charging up to 2 hours after block end
                # This captures charging at Telexstraat after block completion
                extended_block_end = block_end + 7200  # 2 hours after block end
                
                for charge_time, charge_info in charging_info_map[bus_vin].items():
                    if charge_time and block_start <= charge_time <= extended_block_end:
                        location = charge_info.get('location_id', 'N/A')
                        charger = charge_info.get('charger_id', 'N/A')
                        connector = charge_info.get('connector_id', 'N/A')
                        # Only show charging location if charger and connector are not N/A
                        # (meaning charging actually started)
                        if charger != 'N/A' and connector != 'N/A':
                            block_charging_info = f"{location}-{charger}-{connector}"
                            block_charging_matched = True
                            # #region agent log
                            block_charging_debug_info['matched_from'] = 'charging_info_map'
                            block_charging_debug_info['matched_charge_time'] = charge_time
                            block_charging_debug_info['matched_location'] = location
                            # #endregion
                            break  # Use first matching charging session
                
                # If no charging found in extended window, also check charging_sessions_map
                # This is more accurate as it includes complete charging sessions
                if block_charging_info == "-" and bus_vin in charging_sessions_map:
                    for charge_start_time, charge_session in sorted(charging_sessions_map[bus_vin].items()):
                        if charge_start_time and block_start <= charge_start_time <= extended_block_end:
                            location = charge_session.get('location_id', 'N/A')
                            charger = charge_session.get('charger_id', 'N/A')
                            connector = charge_session.get('connector_id', 'N/A')
                            if charger != 'N/A' and connector != 'N/A':
                                block_charging_info = f"{location}-{charger}-{connector}"
                                block_charging_matched = True
                                # #region agent log
                                block_charging_debug_info['matched_from'] = 'charging_sessions_map'
                                block_charging_debug_info['matched_charge_time'] = charge_start_time
                                block_charging_debug_info['matched_location'] = location
                                # #endregion
                                break  # Use first matching charging session
        
        # #region agent log
        # Debug: Log block charging matching
        if not block_charging_matched and bus_vin:
            try:
                debug_log_path = ".cursor/debug.log"
                with open(debug_log_path, "a", encoding="utf-8") as f:
                    block_charging_debug_info['block_start'] = block_data.get('block_start_time')
                    block_charging_debug_info['block_end'] = block_data.get('block_end_time')
                    f.write(json.dumps({
                        "sessionId": "debug-session",
                        "runId": "report-gen",
                        "hypothesisId": "H2",
                        "location": "classified_report_generator.py:819",
                        "message": "Block charging not matched",
                        "data": block_charging_debug_info,
                        "timestamp": datetime.now().timestamp() * 1000
                    }) + "\n")
            except Exception as e:
                pass
        # #endregion
        
        # Check if block was skipped (either at start or first journey was skipped)
        block_skipped = False
        block_skip_info = None
        
        # IMPORTANT: Only mark block as skipped if:
        # 1. There's a block_skipped event, AND
        # 2. There's NO block_assigned event (block was never successfully assigned)
        # If block has bus_number or bus_vin, it means it was assigned, so don't show as skipped
        has_bus_assigned = block_data.get('bus_number') is not None or block_data.get('bus_vin') is not None
        
        # Check if there's a block_assigned event for this block
        has_block_assigned = False
        for log in planning_log:
            if (log.get('block_id') == block_id and 
                log.get('event') == 'block_assigned'):
                has_block_assigned = True
                break
        
        # Only mark as skipped if block was never assigned
        if not has_block_assigned and not has_bus_assigned:
            # Check if block was skipped at start (no bus assigned)
            if block_id in skipped_blocks_map:
                block_skipped = True
                block_skip_info = skipped_blocks_map[block_id]
        # Otherwise check if first journey was skipped
        elif block and block.journeys:
            first_journey = block.journeys[0]
            first_journey_data = block_data['journeys'].get(first_journey.journey_id, {})
            if first_journey_data.get('skipped'):
                block_skipped = True
                block_skip_info = {
                    'time': first_journey_data.get('skip_time'),
                    'soc_percent': first_journey_data.get('skip_soc'),
                    'reason': first_journey_data.get('skip_reason', 'Low SOC at first journey')
                }
        
        # Block row (expandable)
        # Use original_block_id for display if available (for cleaner display in multi-day simulations)
        display_block_id = getattr(block, 'original_block_id', block_id) if block else block_id
        # Aggregate block-level status labels for quick scanning in top-level row.
        has_replacement = any(
            (block_id, jid) in journey_replacement_map
            for jid, _ in sorted_journeys
        )
        has_journey_skipped = any(j.get('skipped', False) for _, j in sorted_journeys)
        has_not_started = any(
            # Treat as not-started only when there is no completion marker AND
            # no point-level execution evidence.
            (j.get('journey_end_time') is None)
            and (not j.get('skipped', False))
            and (not j.get('points'))
            for _, j in sorted_journeys
        )
        block_labels: list[str] = []
        if block_skipped or has_journey_skipped:
            block_labels.append("SKIPPED")
        if has_replacement:
            block_labels.append("REPLACEMENT")
        if has_not_started:
            block_labels.append("NOT_STARTED")
        block_status = ""
        if block_labels:
            labels_str = " | ".join(block_labels)
            block_status = f" <span style=\"color:#b02a37; font-weight:600;\">[{labels_str}]</span>"
        assigned_bus_attr = html.escape(str(block_data['bus_number'])) if block_data.get('bus_number') is not None else "N/A"
        html_rows.append(f"""
        <tr class="block-row" id="block-{block_id_safe}" data-assigned-bus="{assigned_bus_attr}">
            <td class="toggle" onclick="toggleVisibility('block-{block_id_safe}')">
                <span class="icon">▶</span> {display_block_id}{block_status}
            </td>
            <td>{block_distance:.2f}</td>
            <td>{block_start_str}</td>
            <td>{block_end_str}</td>
            <td>{block_data['bus_number'] or 'N/A'}</td>
            <td>{block_soc_str}</td>
            <td>{block_charging_info}</td>
        </tr>""")

        # Add assignment explainability row emitted by depot_return_dispatch strategy.
        explain_info = assignment_explain_map.get(block_id)
        if explain_info:
            explain_time = explain_info.get('time')
            explain_time_str = (
                datetime.fromtimestamp(explain_time).strftime('%Y-%m-%d %H:%M:%S')
                if isinstance(explain_time, (int, float))
                else "N/A"
            )
            strategy_name = html.escape(str(explain_info.get('strategy') or 'N/A'))
            mode_name = html.escape(str(explain_info.get('assignment_mode') or 'N/A'))
            selected_bus = html.escape(str(explain_info.get('selected_bus_number') or 'N/A'))
            selected_point = html.escape(str(explain_info.get('selected_bus_point_id') or 'N/A'))
            selected_soc = explain_info.get('selected_bus_soc_percent')
            selected_soc_str = f"{selected_soc:.2f}" if isinstance(selected_soc, (int, float)) else "N/A"
            origin_pid = html.escape(str(explain_info.get('origin_point_id') or 'N/A'))
            target_distance = explain_info.get('target_distance_km')
            target_distance_str = f"{target_distance:.2f}" if isinstance(target_distance, (int, float)) else "N/A"
            changed = bool(explain_info.get('changed_assignment'))
            changed_label = "是（已改派）" if changed else "否（保持原分配）"

            candidates = explain_info.get('candidates') or []
            rendered_candidates_html: list[str] = []
            for idx, c in enumerate(candidates[:5], start=1):
                bus_nr = html.escape(str(c.get('bus_number', 'N/A')))
                pid = html.escape(str(c.get('point_id', 'N/A')))
                soc = c.get('soc_percent')
                soc_str = f"{soc:.2f}" if isinstance(soc, (int, float)) else "N/A"
                if "score" in c:
                    score = c.get('score')
                    score_str = f"{score:.4f}" if isinstance(score, (int, float)) else "N/A"
                    can_complete = "可完成" if c.get('can_complete') else "不可完成"
                    rendered_candidates_html.append(
                        f"<li>{idx}. Bus <strong>{bus_nr}</strong> @ 点位 <code>{pid}</code>, SOC={soc_str}%, 评分={score_str}, {can_complete}</li>"
                    )
                else:
                    delta = c.get('distance_delta_km')
                    delta_str = f"{delta:.4f}" if isinstance(delta, (int, float)) else "N/A"
                    base = c.get('baseline_distance_km')
                    base_str = f"{base:.2f}" if isinstance(base, (int, float)) else "N/A"
                    rendered_candidates_html.append(
                        f"<li>{idx}. Bus <strong>{bus_nr}</strong> @ 点位 <code>{pid}</code>, SOC={soc_str}%, 距离偏差={delta_str}km, 基线距离={base_str}km</li>"
                    )
            if rendered_candidates_html:
                candidates_html = "<ul style=\"margin: 6px 0 0 18px; padding: 0;\">" + "".join(rendered_candidates_html) + "</ul>"
            else:
                candidates_html = "<span style=\"color:#666;\">无候选数据</span>"

            html_rows.append(f"""
        <tr class="journey-row hidden indent-1" data-parent-id="block-{block_id_safe}" style="background-color: #eef6ff;">
            <td colspan="7" style="padding-left: 30px;">
                <div style="line-height: 1.45;">
                    <strong>🧠 指派解释</strong>
                    <span style="color:#666;">[{strategy_name}/{mode_name}]</span>
                    <span style="color:#666;">@ {explain_time_str}</span>
                    <div style="margin-top: 4px;">
                        <strong>结论：</strong>
                        选择 <strong>Bus {selected_bus}</strong>
                        （当前位置 <code>{selected_point}</code>，SOC {selected_soc_str}%），
                        目标起点 <code>{origin_pid}</code>，目标距离 {target_distance_str}km，
                        是否改派：<strong>{changed_label}</strong>。
                    </div>
                    <div style="margin-top: 6px;">
                        <strong>候选对比（Top 5）：</strong>
                        {candidates_html}
                    </div>
                </div>
            </td>
        </tr>""")
        
        # Add block end charging info row if bus returned to Telexstraat after block completion
        # IMPORTANT: Use the bus from the last journey (in case of bus replacement during block)
        # This needs to be done AFTER sorted_journeys is created, so we'll move this logic after the journey loop
        
        # Add skipped block info row if block was skipped at start
        if block_skipped and block_skip_info:
            skip_time_str = datetime.fromtimestamp(block_skip_info['time']).strftime('%Y-%m-%d %H:%M:%S') if block_skip_info.get('time') else "N/A"
            skip_reason = block_skip_info.get('reason', 'Unknown reason')
            
            # If skip_info has soc_percent, include it; otherwise just show reason
            skip_soc = block_skip_info.get('soc_percent')
            if skip_soc is not None:
                skip_soc_str = f"{skip_soc:.2f}" if isinstance(skip_soc, (int, float)) else "N/A"
                skip_details = f"Time: {skip_time_str}, SOC: {skip_soc_str}%"
            else:
                skip_details = f"Time: {skip_time_str}"
            
            html_rows.append(f"""
        <tr class="journey-row hidden indent-1 skipped-info" data-parent-id="block-{block_id_safe}" style="background-color: #ffebee;">
            <td colspan="7" style="padding-left: 30px;">
                <strong>⚠️ Block Skipped at Start:</strong> {skip_reason} ({skip_details})
            </td>
        </tr>""")
        
        for journey_id, journey_data in sorted_journeys:
            journey = None
            if block:
                journey = next((j for j in block.journeys if j.journey_id == journey_id), None)
            
            # Check if this is a return journey or block end return journey
            is_return_journey = (journey and hasattr(journey, 'journey_type') and 
                                journey.journey_type == "RETURN_TO_TELEXSTRAAT")
            is_block_end_return_journey = (journey and hasattr(journey, 'journey_type') and 
                                          journey.journey_type == "BLOCK_END_RETURN_TO_TELEXSTRAAT")
            is_any_return_journey = is_return_journey or is_block_end_return_journey
            
            # Check if this journey was replaced and populate replacement info
            replacement_key = (block_id, journey_id)
            if replacement_key in journey_replacement_map:
                replacement_info = journey_replacement_map[replacement_key]
                journey_data['replacement_bus_number'] = replacement_info.get('replacement_bus_number')
                journey_data['replacement_bus_vin'] = replacement_info.get('replacement_bus_vin')
                journey_data['original_bus_number'] = replacement_info.get('original_bus_number')
                journey_data['original_bus_vin'] = replacement_info.get('original_bus_vin')
                journey_data['replacement_time'] = replacement_info.get('time')
                journey_data['replacement_reason'] = replacement_info.get('reason', 'Journey replacement')
            
            # Check if this is a return journey and populate return journey info
            return_journey_key = (block_id, journey_id)
            if return_journey_key in return_journey_map:
                return_journey_info = return_journey_map[return_journey_key]
                journey_data['is_return_journey'] = True
                journey_data['return_journey_bus_number'] = return_journey_info.get('bus_number')
                journey_data['return_journey_bus_vin'] = return_journey_info.get('bus_vin')
                journey_data['return_journey_time'] = return_journey_info.get('time')
            elif return_journey_key in block_end_return_journey_map:
                # Block end return journey
                block_end_return_journey_info = block_end_return_journey_map[return_journey_key]
                journey_data['is_return_journey'] = True
                journey_data['is_block_end_return_journey'] = True
                journey_data['return_journey_bus_number'] = block_end_return_journey_info.get('bus_number')
                journey_data['return_journey_bus_vin'] = block_end_return_journey_info.get('bus_vin')
                journey_data['return_journey_time'] = block_end_return_journey_info.get('time')
            elif is_any_return_journey:
                # Journey is a return journey or block end return journey but no event found - use journey_type to identify
                journey_data['is_return_journey'] = True
                if is_block_end_return_journey:
                    journey_data['is_block_end_return_journey'] = True
            
            # If journey_start_time is None, try to get it from world or from first point
            if journey_data['journey_start_time'] is None:
                if journey and journey.first_departure_datetime:
                    journey_data['journey_start_time'] = journey.first_departure_datetime.timestamp()
                elif journey_data['points']:
                    # Use first point's time as journey start time
                    sorted_points = sorted(
                        journey_data['points'],
                        key=lambda p: p['time'] if p['time'] is not None else float('inf')
                    )
                    if sorted_points and sorted_points[0].get('time'):
                        journey_data['journey_start_time'] = sorted_points[0]['time']
            
            # If journey_end_time is None, try to get it from world or from last point
            if journey_data['journey_end_time'] is None:
                if journey and journey.points:
                    last_point = journey.points[-1]
                    if last_point.arrival_datetime:
                        journey_data['journey_end_time'] = last_point.arrival_datetime.timestamp()
                elif journey_data['points']:
                    # Use last point's time as journey end time
                    sorted_points = sorted(
                        journey_data['points'],
                        key=lambda p: p['time'] if p['time'] is not None else float('inf')
                    )
                    if sorted_points and sorted_points[-1].get('time'):
                        journey_data['journey_end_time'] = sorted_points[-1]['time']
            
            # Calculate journey distance
            journey_distance = 0.0
            if journey:
                for point in journey.points:
                    if point.distance_to_next_m:
                        journey_distance += point.distance_to_next_m / 1000.0
            elif journey_data['points']:
                # Calculate from points data if journey not available
                for point in journey_data['points']:
                    if point.get('distance_to_next_m'):
                        journey_distance += point['distance_to_next_m'] / 1000.0
            
            journey_id_safe = journey_id.replace(':', '-').replace('/', '-').replace(' ', '-')
            journey_start_str = datetime.fromtimestamp(journey_data['journey_start_time']).strftime('%Y-%m-%d %H:%M:%S') if journey_data['journey_start_time'] else "N/A"
            journey_end_str = datetime.fromtimestamp(journey_data['journey_end_time']).strftime('%Y-%m-%d %H:%M:%S') if journey_data['journey_end_time'] else "N/A"
            
            # Find the last SOC in the journey (from the last point)
            journey_last_soc = None
            sorted_points = sorted(
                journey_data['points'],
                key=lambda p: p['time'] if p['time'] is not None else float('inf')
            )
            if sorted_points:
                last_point = sorted_points[-1]
                if last_point.get('soc_percent') is not None:
                    journey_last_soc = last_point['soc_percent']
            
            journey_soc_str = f"{journey_last_soc:.2f}" if journey_last_soc is not None else "-"
            
            # Find charging info for the journey (charging after journey end, before next journey start)
            journey_charging_info = "-"
            bus_vin = block_data.get('bus_vin')
            journey_end_time = journey_data.get('journey_end_time')
            if bus_vin and journey_end_time and bus_vin in charging_info_map:
                # Find charging sessions that start after journey end
                # Look for next journey start time to determine the time window
                next_journey_start = None
                journey_index = sorted_journeys.index((journey_id, journey_data))
                if journey_index < len(sorted_journeys) - 1:
                    next_journey_id, next_journey_data = sorted_journeys[journey_index + 1]
                    next_journey_start = next_journey_data.get('journey_start_time')
                
                # Find charging sessions between journey_end and next_journey_start
                # For last journey in block: allow charging until next block starts (or until 100% SOC)
                # CRITICAL: Only match charging that happens AFTER journey_end and BEFORE next_journey_start
                # Do NOT use extended time windows that can match charging from other journeys
                is_last_journey_in_block = (journey_index == len(sorted_journeys) - 1)
                
                # For last journey in block, find next block start time
                next_block_start_time = None
                if is_last_journey_in_block:
                    # Find the next block for the same bus
                    current_block_index = sorted_blocks.index((block_id, block_data))
                    if current_block_index < len(sorted_blocks) - 1:
                        # Check if next block is for the same bus
                        for next_block_id, next_block_data in sorted_blocks[current_block_index + 1:]:
                            if next_block_data.get('bus_vin') == bus_vin:
                                next_block_start_time = next_block_data.get('block_start_time')
                                break
                
                # Determine time limit for charging matching
                if next_journey_start:
                    # There's a next journey in the same block
                    time_limit = next_journey_start
                elif next_block_start_time:
                    # Last journey in block, but there's a next block for the same bus
                    time_limit = next_block_start_time
                else:
                    # Last journey in block, and no next block - allow charging until 100% (no time limit)
                    # Set a very large time limit to allow all charging after journey_end
                    time_limit = journey_end_time + 86400  # 24 hours after journey end (effectively no limit)
                
                if time_limit:
                    # Strict time window: only match charging between journey_end and time_limit
                    # Use a small buffer (5 minutes) to account for timing precision
                    window_start = journey_end_time - 300  # 5 minutes before (small buffer)
                    window_end = time_limit + 300  # 5 minutes after (small buffer)
                    for charge_time, charge_info in sorted(charging_info_map[bus_vin].items()):
                        # CRITICAL: Only match charging that happens AFTER journey_end (not before)
                        if charge_time and window_start <= charge_time <= window_end and charge_time >= journey_end_time:
                            # For last journey in block with next block, ensure charging doesn't extend beyond next block start
                            if is_last_journey_in_block and next_block_start_time and charge_time > next_block_start_time:
                                continue
                            
                            location = charge_info.get('location_id', 'N/A')
                            charger = charge_info.get('charger_id', 'N/A')
                            connector = charge_info.get('connector_id', 'N/A')
                            # Only show charging location if charger and connector are not N/A
                            # (meaning charging actually started)
                            if charger != 'N/A' and connector != 'N/A':
                                journey_charging_info = f"{location}-{charger}-{connector}"
                                break  # Use first matching charging session
            
            # Check if journey was skipped
            journey_skipped = journey_data.get('skipped', False)
            journey_skip_info = None
            if journey_skipped:
                journey_skip_info = {
                    'time': journey_data.get('skip_time'),
                    'soc_percent': journey_data.get('skip_soc'),
                    'reason': journey_data.get('skip_reason', 'Low SOC')
                }
            
            # Journey row (expandable, nested under block)
            # Use original_journey_id for display if available (for cleaner display in multi-day simulations)
            display_journey_id = getattr(journey, 'original_journey_id', journey_id) if journey else journey_id
            journey_status = " ⚠️ SKIPPED" if journey_skipped else ""
            journey_row_class = "journey-row hidden indent-1" + (" skipped-journey" if journey_skipped else "")
            journey_type_value = str(getattr(journey, 'journey_type', '') or '').strip().lower() if journey else ""
            journey_id_style = ""
            if journey_type_value == "servicejourney":
                journey_id_style = "color:#1b8f3a; font-weight:600;"
            elif journey_type_value == "deadrun":
                journey_id_style = "color:#c62828; font-weight:600;"
            display_journey_id_html = html.escape(str(display_journey_id))
            if journey_id_style:
                display_journey_id_html = f"<span style=\"{journey_id_style}\">{display_journey_id_html}</span>"
            
            # For return journey, use the original bus number (not replacement bus)
            # For regular journey with replacement, use replacement bus number
            if journey_data.get('is_return_journey'):
                # Return journey: use the bus that executes the return journey
                journey_bus_number = journey_data.get('return_journey_bus_number') or journey_data.get('bus_number') or block_data['bus_number'] or 'N/A'
            else:
                # Regular journey: use replacement bus if available, otherwise use journey bus
                journey_bus_number = journey_data.get('replacement_bus_number') or journey_data.get('bus_number') or block_data['bus_number'] or 'N/A'
            
            html_rows.append(f"""
        <tr class="{journey_row_class}" data-parent-id="block-{block_id_safe}" id="journey-{journey_id_safe}">
            <td class="toggle" onclick="toggleVisibility('journey-{journey_id_safe}')">
                <span class="icon">▶</span> {display_journey_id_html}{journey_status}
            </td>
            <td>{journey_distance:.2f}</td>
            <td>{journey_start_str}</td>
            <td>{journey_end_str}</td>
            <td>{journey_bus_number}</td>
            <td>{journey_soc_str}</td>
            <td>{journey_charging_info}</td>
        </tr>""")
            
            # Add journey replacement info row if journey was replaced
            if journey_data.get('replacement_bus_number'):
                replacement_time_str = datetime.fromtimestamp(journey_data['replacement_time']).strftime('%Y-%m-%d %H:%M:%S') if journey_data.get('replacement_time') else "N/A"
                original_bus = journey_data.get('original_bus_number', 'N/A')
                replacement_bus = journey_data.get('replacement_bus_number', 'N/A')
                replacement_reason = journey_data.get('replacement_reason', 'Journey replacement')
                
                # Find charging info for original bus at Telexstraat after replacement
                original_bus_charging_info = ""
                if original_bus != 'N/A' and world:
                    # First try to use original_bus_vin from journey_data (from journey_replacement_map)
                    original_bus_vin = journey_data.get('original_bus_vin')
                    
                    # If not found, find bus VIN from bus_number (handle both int and string types)
                    if not original_bus_vin:
                        original_bus_num = int(original_bus) if isinstance(original_bus, (int, str)) and str(original_bus).isdigit() else original_bus
                        for bus in world.buses:
                            if bus.vehicle_number == original_bus_num:
                                original_bus_vin = bus.vin_number
                                break
                    
                    if original_bus_vin and original_bus_vin in charging_info_map:
                        replacement_time = journey_data.get('replacement_time')
                        if replacement_time:
                            # Look for charging at Telexstraat after replacement time (within 4 hours to catch delayed charging)
                            time_window_end = replacement_time + 14400  # 4 hours
                            for charge_time, charge_info in sorted(charging_info_map[original_bus_vin].items()):
                                if charge_time and charge_time >= replacement_time and charge_time <= time_window_end:
                                    location = charge_info.get('location_id', 'N/A')
                                    if location == 'Telexstraat':
                                        charger = charge_info.get('charger_id', 'N/A')
                                        connector = charge_info.get('connector_id', 'N/A')
                                        if charger != 'N/A' and connector != 'N/A':
                                            charge_time_str = datetime.fromtimestamp(charge_time).strftime('%Y-%m-%d %H:%M:%S')
                                            original_bus_charging_info = f" | Bus {original_bus} charged at Telexstraat: {charger}-{connector} (Time: {charge_time_str})"
                                            break
                
                html_rows.append(f"""
        <tr class="journey-row hidden indent-2 replacement-info" data-parent-id="journey-{journey_id_safe}" style="background-color: #fff3e0;">
            <td colspan="7" style="padding-left: 50px;">
                <strong>🔄 Journey Replacement:</strong> Bus {original_bus} → Bus {replacement_bus} ({replacement_reason}, Time: {replacement_time_str}){original_bus_charging_info}
            </td>
        </tr>""")
            
            # Add skipped journey info row if journey was skipped
            if journey_skipped and journey_skip_info:
                skip_time_str = datetime.fromtimestamp(journey_skip_info['time']).strftime('%Y-%m-%d %H:%M:%S') if journey_skip_info.get('time') else "N/A"
                skip_soc = journey_skip_info.get('soc_percent')
                skip_soc_str = f"{skip_soc:.2f}" if isinstance(skip_soc, (int, float)) else "N/A"
                # Check if this was the first journey (block skipped at start) or later journey (skipped during execution)
                is_first_journey = (journey == block.journeys[0] if block and block.journeys else False)
                skip_type = "at start" if is_first_journey else "during execution"
                html_rows.append(f"""
        <tr class="point-row hidden indent-2 skipped-info" data-parent-id="journey-{journey_id_safe}" style="background-color: #ffebee;">
            <td colspan="7" style="padding-left: 50px;">
                <strong>⚠️ Journey Skipped {skip_type}:</strong> {journey_skip_info.get('reason', 'Low SOC')} 
                (Time: {skip_time_str}, SOC: {skip_soc_str}%)
            </td>
        </tr>""")
            
            # Point rows (nested under journey)
            journey_index = sorted_journeys.index((journey_id, journey_data))
            is_last_journey_in_block = (journey_index == len(sorted_journeys) - 1)
            
            # For return journey, check if first point should be skipped (if it's the same as previous journey's last point)
            skip_first_point = False
            if journey_data.get('is_return_journey') and journey_index > 0:
                # Get previous journey's last point
                prev_journey_id, prev_journey_data = sorted_journeys[journey_index - 1]
                if prev_journey_data.get('points'):
                    prev_sorted_points = sorted(
                        prev_journey_data['points'],
                        key=lambda p: p['time'] if p['time'] is not None else float('inf')
                    )
                    if prev_sorted_points:
                        prev_last_point = prev_sorted_points[-1]
                        # Check if current journey's first point is the same as previous journey's last point
                        if sorted_points and sorted_points[0].get('point_id') == prev_last_point.get('point_id'):
                            skip_first_point = True
            
            # Create a list of points to display (excluding skipped first point)
            points_to_display = sorted_points
            if skip_first_point and sorted_points:
                points_to_display = sorted_points[1:]  # Skip first point
            else:
                points_to_display = sorted_points

            # Keep report semantics clear: each journey must show at least origin and destination records.
            if len(sorted_points) >= 2:
                origin_point = sorted_points[0]
                destination_point = sorted_points[-1]
                has_origin = any(
                    p.get('point_id') == origin_point.get('point_id') and p.get('time') == origin_point.get('time')
                    for p in points_to_display
                )
                has_destination = any(
                    p.get('point_id') == destination_point.get('point_id') and p.get('time') == destination_point.get('time')
                    for p in points_to_display
                )
                if not has_origin:
                    points_to_display = [origin_point] + points_to_display
                if not has_destination:
                    points_to_display = points_to_display + [destination_point]
            
            for point_index, point in enumerate(points_to_display):
                point_id_safe = str(point['point_id']).replace(':', '-').replace('/', '-').replace(' ', '-')
                point_time_str = datetime.fromtimestamp(point['time']).strftime('%Y-%m-%d %H:%M:%S') if point['time'] else "N/A"
                
                # Get distance to next point
                distance_km = 0.0
                if journey:
                    point_obj = next((p for p in journey.points if p.point_id == point['point_id']), None)
                    if point_obj and point_obj.distance_to_next_m:
                        distance_km = point_obj.distance_to_next_m / 1000.0
                
                # Find charging info for the point (charging after point arrival, before next point)
                # IMPORTANT: Do NOT match charging that happens after journey end (those should only show at journey level)
                # Also, only match charging if the charging location matches the point's location (point_id match)
                point_charging_info = "-"
                bus_vin = block_data.get('bus_vin')
                point_time = point.get('time')
                is_last_point = (point_index == len(points_to_display) - 1)
                
                # Get point object to check charging_location
                point_obj = None
                if journey:
                    point_obj = next((p for p in journey.points if p.point_id == point['point_id']), None)
                
                # Check if point has charging location
                point_has_charger = (point_obj and point_obj.charging_location is not None)
                
                if bus_vin and point_time:
                    # First, try to find charging_started event
                    if bus_vin in charging_info_map:
                        # Find next point time
                        next_point_time = None
                        journey_end_time = journey_data.get('journey_end_time')
                        
                        if point_index < len(points_to_display) - 1:
                            next_point = points_to_display[point_index + 1]
                            next_point_time = next_point.get('time')
                        elif is_last_point:
                            # For last point, check charging that may start after journey end (bus may be in queue)
                            # Look for next journey start time to determine the time window
                            next_journey_start = None
                            if journey_index < len(sorted_journeys) - 1:
                                next_journey_id, next_journey_data = sorted_journeys[journey_index + 1]
                                next_journey_start = next_journey_data.get('journey_start_time')
                            
                            # For last point, allow checking charging that starts after journey end
                            # but before next journey start (bus may be in queue waiting for connector)
                            if next_journey_start:
                                next_point_time = next_journey_start
                            else:
                                # No next journey, use a longer time window (2 hours) to catch delayed charging
                                next_point_time = point_time + 7200  # 2 hours after point arrival
                        
                        if next_point_time:
                            # CRITICAL: Only match charging if the point has a charging location
                            # If point has no charging location, it cannot have charging events
                            if point_obj and point_obj.charging_location:
                                point_location_id = point_obj.charging_location.location_id
                                
                                for charge_time, charge_info in charging_info_map[bus_vin].items():
                                    # Only match charging that happens:
                                    # 1. After point arrival
                                    # 2. Before next point/next journey start
                                    # 3. For last point, allow charging that starts after journey end (bus in queue)
                                    if charge_time and point_time <= charge_time <= next_point_time:
                                        # CRITICAL: Only match charging if the charging location matches the point's location
                                        # This prevents matching charging at Telexstraat to point Centraal Station
                                        charging_location_id = charge_info.get('location_id', 'N/A')
                                        # Only match if location_id matches
                                        if charging_location_id != point_location_id:
                                            continue  # Skip charging at different location
                                        
                                        location = charge_info.get('location_id', 'N/A')
                                        charger = charge_info.get('charger_id', 'N/A')
                                        connector = charge_info.get('connector_id', 'N/A')
                                        # Only show charging location if charger and connector are not N/A
                                        # (meaning charging actually started)
                                        if charger != 'N/A' and connector != 'N/A':
                                            point_charging_info = f"{location}-{charger}-{connector}"
                                            break  # Use first matching charging session
                            # If point has no charging location, do not match any charging events
                            # This prevents showing charging at wrong locations (e.g., Telexstraat at Centraal Station)
                    
                    # If no charging_started found in point time window, check if charging was requested
                    # For last point, also check charging that starts after journey end (bus may be in queue)
                    if point_charging_info == "-" and point_has_charger and bus_vin in charging_requested_map:
                        point_location_id = point_obj.charging_location.location_id if point_obj and point_obj.charging_location else None
                        if point_location_id:
                            # Check for charging_requested events at this point's location
                            next_point_time = None
                            journey_end_time = journey_data.get('journey_end_time')
                            
                            if point_index < len(points_to_display) - 1:
                                next_point = points_to_display[point_index + 1]
                                next_point_time = next_point.get('time')
                            elif is_last_point:
                                # For last point, check charging that may start after journey end
                                # Look for next journey start time to determine the time window
                                next_journey_start = None
                                if journey_index < len(sorted_journeys) - 1:
                                    next_journey_id, next_journey_data = sorted_journeys[journey_index + 1]
                                    next_journey_start = next_journey_data.get('journey_start_time')
                                
                                # For last point, allow checking charging that starts after journey end
                                # but before next journey start (bus may be in queue)
                                if next_journey_start:
                                    next_point_time = next_journey_start
                                else:
                                    # No next journey, use a longer time window (2 hours) to catch delayed charging
                                    next_point_time = point_time + 7200  # 2 hours after point arrival
                            
                            if next_point_time:
                                for req_time, req_info in charging_requested_map[bus_vin].items():
                                    # Check if request is within the time window
                                    if req_time and point_time <= req_time <= next_point_time:
                                        # For last point, allow requests after journey end (bus may be in queue)
                                        # but ensure it's before next journey start
                                        if is_last_point and journey_end_time:
                                            if req_time > journey_end_time:
                                                # Request after journey end is OK for last point
                                                # But check if it's before next journey start
                                                if next_journey_start and req_time > next_journey_start:
                                                    continue
                                        
                                        # Check if location matches
                                        if req_info.get('location_id') == point_location_id:
                                            # Check if there's a matching charging_started event
                                            # For last point, check charging that may start after journey end (bus in queue)
                                            has_started = False
                                            if bus_vin in charging_info_map:
                                                for charge_time, charge_info in charging_info_map[bus_vin].items():
                                                    # Check if charging location matches
                                                    if charge_info.get('location_id') != point_location_id:
                                                        continue
                                                    
                                                    # For last point, allow charging that starts after journey end but before next journey
                                                    if is_last_point:
                                                        # Charging must be after request time and before next journey start
                                                        if (charge_time >= req_time and 
                                                            charge_time <= next_point_time):
                                                            # Valid charging - bus was in queue and started charging
                                                            has_started = True
                                                            # Update point_charging_info with the actual charging info
                                                            location = charge_info.get('location_id', 'N/A')
                                                            charger = charge_info.get('charger_id', 'N/A')
                                                            connector = charge_info.get('connector_id', 'N/A')
                                                            if charger != 'N/A' and connector != 'N/A':
                                                                point_charging_info = f"{location}-{charger}-{connector}"
                                                            break
                                                    else:
                                                        # For non-last points, charging must start within 5 minutes of request
                                                        if abs(charge_time - req_time) <= 300:  # 5 minutes
                                                            has_started = True
                                                            break
                                            
                                            if not has_started:
                                                # Charging was requested but not started within the time window
                                                # This means charger was unavailable and bus didn't get to charge
                                                point_charging_info = "Charger unavailable"
                                                break
                
                # For last point of a journey, optionally check if bus goes to Telexstraat after journey end.
                # IMPORTANT: only do this for return-to-garage semantics; otherwise we may incorrectly
                # attach block-end depot charging to a normal journey endpoint.
                is_telexstraat_destination_point = (
                    str(point.get('point_id', '')) == '30002'
                    or 'Telexstraat' in str(point.get('point_name', ''))
                )
                allow_post_journey_telexstraat_overlay = bool(
                    journey_data.get('is_return_journey') or is_telexstraat_destination_point
                )
                if is_last_point and point_charging_info == "-" and allow_post_journey_telexstraat_overlay:
                    journey_end_time = journey_data.get('journey_end_time')
                    
                    # Special handling for return journey: use return_journey_bus_vin
                    if journey_data.get('is_return_journey'):
                        # For return journey, use the bus that executes the return journey
                        bus_to_check_vin = journey_data.get('return_journey_bus_vin') or journey_data.get('bus_vin')
                    else:
                        # For regular journey, get bus info (replacement bus if journey was replaced, otherwise journey's bus)
                        journey_bus_vin = journey_data.get('replacement_bus_vin') or journey_data.get('bus_vin')
                        journey_bus_number = journey_data.get('replacement_bus_number') or journey_data.get('bus_number')
                        
                        # Check if this is the original bus (from block start) that needs to return to Telexstraat
                        # This happens when a bus is replaced during a journey and the original bus returns to Telexstraat
                        original_block_bus = block_data.get('bus_number')
                        original_block_bus_vin = block_data.get('bus_vin')
                        
                        # If the journey bus is different from the original block bus, check if original bus goes to Telexstraat
                        # Otherwise, check if the journey bus goes to Telexstraat
                        bus_to_check_vin = None
                        if (original_block_bus and original_block_bus_vin and journey_bus_number and 
                            str(original_block_bus) != str(journey_bus_number)):
                            # Original bus was replaced, check if original bus goes to Telexstraat
                            bus_to_check_vin = original_block_bus_vin
                        elif journey_bus_vin:
                            # No replacement, check if journey bus goes to Telexstraat
                            bus_to_check_vin = journey_bus_vin
                    
                    # For return journey / Telexstraat destination, check both maps.
                    # Use a longer time window to catch delayed charging.
                    if bus_to_check_vin and journey_end_time:
                        time_window = 14400 if journey_data.get('is_return_journey') else 7200
                        time_window_end = journey_end_time + time_window
                        
                        # First, try charging_sessions_map (more accurate, includes end time).
                        if bus_to_check_vin in charging_sessions_map:
                            for charge_start_time, charge_session in sorted(charging_sessions_map[bus_to_check_vin].items()):
                                if charge_start_time and charge_start_time >= journey_end_time and charge_start_time <= time_window_end:
                                    location = charge_session.get('location_id', 'N/A')
                                    # Check for Telexstraat (exact match or contains "Telexstraat")
                                    if location == 'Telexstraat' or (isinstance(location, str) and 'Telexstraat' in location):
                                        charger = charge_session.get('charger_id', 'N/A')
                                        connector = charge_session.get('connector_id', 'N/A')
                                        if charger != 'N/A' and connector != 'N/A':
                                            point_charging_info = f"{charger}-{connector}"
                                            break  # Only show first charging session
                        
                        # If not found in charging_sessions_map, try charging_info_map.
                        if point_charging_info == "-" and bus_to_check_vin in charging_info_map:
                            # Fallback for return journey / Telexstraat destination.
                            for charge_time, charge_info in sorted(charging_info_map[bus_to_check_vin].items()):
                                if charge_time and charge_time >= journey_end_time and charge_time <= time_window_end:
                                    location = charge_info.get('location_id', 'N/A')
                                    # Check for Telexstraat (exact match or contains "Telexstraat")
                                    if location == 'Telexstraat' or (isinstance(location, str) and 'Telexstraat' in location):
                                        charger = charge_info.get('charger_id', 'N/A')
                                        connector = charge_info.get('connector_id', 'N/A')
                                        if charger != 'N/A' and connector != 'N/A':
                                            point_charging_info = f"{charger}-{connector}"
                                            break  # Only show first charging session
                        
                        # #region agent log
                        # Debug: Log when charging info is not found for journey ending at Telexstraat
                        if point_charging_info == "-" and bus_to_check_vin and journey_end_time:
                            try:
                                debug_log_path = ".cursor/debug.log"
                                # Check if this is a journey ending at Telexstraat
                                is_telexstraat_journey = False
                                if is_last_point and points_to_display:
                                    last_point = points_to_display[-1]
                                    point_name = last_point.get('point_name', '')
                                    point_id = last_point.get('point_id', '')
                                    if 'Telexstraat' in point_name or point_id == '30002':
                                        is_telexstraat_journey = True
                                
                                with open(debug_log_path, "a", encoding="utf-8") as f:
                                    # Check if charging exists in maps
                                    has_charging_sessions = bus_to_check_vin in charging_sessions_map
                                    has_charging_info = bus_to_check_vin in charging_info_map
                                    charging_sessions_count = len(charging_sessions_map.get(bus_to_check_vin, {}))
                                    charging_info_count = len(charging_info_map.get(bus_to_check_vin, {}))
                                    
                                    # Check for any Telexstraat charging in time window
                                    telexstraat_charging_found = False
                                    telexstraat_charging_details = []
                                    if has_charging_sessions:
                                        for charge_start_time, charge_session in charging_sessions_map[bus_to_check_vin].items():
                                            location_id = charge_session.get('location_id', 'N/A')
                                            if (charge_start_time and 
                                                charge_start_time >= journey_end_time and 
                                                charge_start_time <= time_window_end):
                                                if location_id == 'Telexstraat' or (isinstance(location_id, str) and 'Telexstraat' in location_id):
                                                    telexstraat_charging_found = True
                                                    telexstraat_charging_details.append({
                                                        'start_time': charge_start_time,
                                                        'location_id': location_id,
                                                        'charger_id': charge_session.get('charger_id'),
                                                        'connector_id': charge_session.get('connector_id')
                                                    })
                                    
                                    # Also check charging_info_map
                                    telexstraat_info_found = False
                                    if has_charging_info:
                                        for charge_time, charge_info in charging_info_map[bus_to_check_vin].items():
                                            location_id = charge_info.get('location_id', 'N/A')
                                            if (charge_time and 
                                                charge_time >= journey_end_time and 
                                                charge_time <= time_window_end):
                                                if location_id == 'Telexstraat' or (isinstance(location_id, str) and 'Telexstraat' in location_id):
                                                    telexstraat_info_found = True
                                                    break
                                    
                                    f.write(json.dumps({
                                        "sessionId": "debug-session",
                                        "runId": "report-gen",
                                        "hypothesisId": "H4",
                                        "location": "classified_report_generator.py:1550",
                                        "message": "Charging info not found for journey ending at Telexstraat",
                                        "data": {
                                            "journey_id": journey_id,
                                            "is_telexstraat_journey": is_telexstraat_journey,
                                            "is_return_journey": journey_data.get('is_return_journey'),
                                            "is_block_end_return_journey": journey_data.get('is_block_end_return_journey'),
                                            "bus_to_check_vin": bus_to_check_vin,
                                            "journey_end_time": journey_end_time,
                                            "time_window_end": time_window_end,
                                            "has_charging_sessions": has_charging_sessions,
                                            "has_charging_info": has_charging_info,
                                            "charging_sessions_count": charging_sessions_count,
                                            "charging_info_count": charging_info_count,
                                            "telexstraat_charging_found": telexstraat_charging_found,
                                            "telexstraat_info_found": telexstraat_info_found,
                                            "telexstraat_charging_details": telexstraat_charging_details[:3]
                                        },
                                        "timestamp": datetime.now().timestamp() * 1000
                                    }) + "\n")
                            except Exception as e:
                                pass
                        # #endregion
                
                # For last point of last journey in block, optionally show Block End Charging at Telexstraat.
                # Keep this only for return-to-garage/Telexstraat-destination points to avoid leakage into
                # regular journey endpoints.
                if is_last_point and is_last_journey_in_block and not block_skipped and block_data.get('block_end_time'):
                    if point_charging_info == "-" and allow_post_journey_telexstraat_overlay:  # Only check if not already set
                        block_end_time = block_data.get('block_end_time')
                        # Get bus info from the last journey (this is the bus that actually completed the block)
                        last_journey_bus_vin = journey_data.get('replacement_bus_vin') or journey_data.get('bus_vin') or block_data.get('bus_vin')
                        if last_journey_bus_vin and last_journey_bus_vin in charging_sessions_map:
                            # Find charging at Telexstraat after block end (within 2 hours)
                            time_window_end = block_end_time + 7200  # 2 hours
                            for charge_start_time, charge_session in sorted(charging_sessions_map[last_journey_bus_vin].items()):
                                if charge_start_time and charge_start_time >= block_end_time and charge_start_time <= time_window_end:
                                    location = charge_session.get('location_id', 'N/A')
                                    # Check for Telexstraat (exact match or contains "Telexstraat")
                                    if location == 'Telexstraat' or (isinstance(location, str) and 'Telexstraat' in location):
                                        charger = charge_session.get('charger_id', 'N/A')
                                        connector = charge_session.get('connector_id', 'N/A')
                                        if charger != 'N/A' and connector != 'N/A':
                                            point_charging_info = f"{charger}-{connector}"
                                            break  # Only show first charging session
                
                # Format SOC safely (handle None values)
                soc_value = point.get('soc_percent')
                soc_str = f"{soc_value:.2f}" if soc_value is not None and isinstance(soc_value, (int, float)) else "-"
                
                # For return journey, use the original bus number (not replacement bus)
                # For regular journey with replacement, use replacement bus number
                if journey_data.get('is_return_journey'):
                    # Return journey: use the bus that executes the return journey
                    point_bus_number = journey_data.get('return_journey_bus_number') or journey_data.get('bus_number') or block_data['bus_number'] or 'N/A'
                else:
                    # Regular journey: use replacement bus if available, otherwise use journey bus
                    point_bus_number = journey_data.get('replacement_bus_number') or journey_data.get('bus_number') or block_data['bus_number'] or 'N/A'
                
                html_rows.append(f"""
        <tr class="point-row hidden indent-2" data-parent-id="journey-{journey_id_safe}">
            <td>{point['point_name']} ({point['point_id']})</td>
            <td>{distance_km:.2f}</td>
            <td>{point_time_str}</td>
            <td>{point_time_str}</td>
            <td>{point_bus_number}</td>
            <td>{soc_str}</td>
            <td>{point_charging_info}</td>
        </tr>""")
            
            # For journey replacement, add charging point record for original bus at Telexstraat
            # Check if we have any points to display (after skipping first point if needed)
            has_points_to_display = len(points_to_display) > 0 if skip_first_point else len(sorted_points) > 0
            if journey_data.get('replacement_bus_number') and has_points_to_display:
                # Get the last point index in points_to_display
                last_displayed_point_index = len(points_to_display) - 1 if skip_first_point else len(sorted_points) - 1
                is_last_point_for_replacement = True  # This is after the loop, so it's the last point
                original_bus = journey_data.get('original_bus_number', 'N/A')
                original_bus_vin = journey_data.get('original_bus_vin')
                replacement_time = journey_data.get('replacement_time')
                
                if original_bus != 'N/A' and original_bus_vin and replacement_time:
                    # Find charging session for original bus at Telexstraat after replacement
                    if original_bus_vin in charging_sessions_map:
                        time_window_end = replacement_time + 14400  # 4 hours
                        for charge_start_time, charge_session in sorted(charging_sessions_map[original_bus_vin].items()):
                            if charge_start_time and charge_start_time >= replacement_time and charge_start_time <= time_window_end:
                                location = charge_session.get('location_id', 'N/A')
                                if location == 'Telexstraat':
                                    charger = charge_session.get('charger_id', 'N/A')
                                    connector = charge_session.get('connector_id', 'N/A')
                                    end_time = charge_session.get('end_time')
                                    end_soc = charge_session.get('end_soc')
                                    
                                    if charger != 'N/A' and connector != 'N/A' and end_time:
                                        # Find Telexstraat point info from world
                                        telexstraat_point_name = "Garage Telexstraat"
                                        telexstraat_point_id = "30002"
                                        if world:
                                            # Try to find Telexstraat location
                                            for loc_id, location_obj in world.locations.items():
                                                if loc_id == 'Telexstraat' and hasattr(location_obj, 'point_id'):
                                                    telexstraat_point_id = str(location_obj.point_id)
                                                    if hasattr(location_obj, 'name'):
                                                        telexstraat_point_name = location_obj.name
                                                    break
                                        
                                        charge_start_str = datetime.fromtimestamp(charge_start_time).strftime('%Y-%m-%d %H:%M:%S')
                                        charge_end_str = datetime.fromtimestamp(end_time).strftime('%Y-%m-%d %H:%M:%S')
                                        end_soc_str = f"{end_soc:.2f}" if end_soc is not None and isinstance(end_soc, (int, float)) else "-"
                                        
                                        html_rows.append(f"""
        <tr class="point-row hidden indent-2" data-parent-id="journey-{journey_id_safe}" style="background-color: #fff3e0;">
            <td>{telexstraat_point_name} ({telexstraat_point_id})</td>
            <td>0.00</td>
            <td>{charge_start_str}</td>
            <td>{charge_end_str}</td>
            <td>{original_bus}</td>
            <td>{end_soc_str}</td>
            <td>{charger}-{connector}</td>
        </tr>""")
                                        break  # Only show first charging session
            
            # For last journey in block, if the original bus (from block start) was replaced in a previous journey,
            # add charging record for the original bus after this journey ends
            # Check if we have any points to display (after skipping first point if needed)
            has_points_to_display = len(points_to_display) > 0 if skip_first_point else len(sorted_points) > 0
            if has_points_to_display and is_last_journey_in_block and not block_skipped:
                # Check if any journey in this block had a replacement
                # If so, the original bus (block_data['bus_number']) should return to Telexstraat after the last journey
                original_block_bus = block_data.get('bus_number')
                original_block_bus_vin = block_data.get('bus_vin')
                last_journey_bus = journey_data.get('replacement_bus_number') or journey_data.get('bus_number')
                
                # If original block bus is different from last journey bus, it means original bus was replaced
                # and should return to Telexstraat after the last journey
                if (original_block_bus and original_block_bus_vin and 
                    last_journey_bus and str(original_block_bus) != str(last_journey_bus)):
                    journey_end_time = journey_data.get('journey_end_time')
                    if journey_end_time and original_block_bus_vin in charging_sessions_map:
                        # Find charging at Telexstraat after journey end (within 4 hours)
                        time_window_end = journey_end_time + 14400  # 4 hours
                        for charge_start_time, charge_session in sorted(charging_sessions_map[original_block_bus_vin].items()):
                            if charge_start_time and charge_start_time >= journey_end_time and charge_start_time <= time_window_end:
                                location = charge_session.get('location_id', 'N/A')
                                if location == 'Telexstraat':
                                    charger = charge_session.get('charger_id', 'N/A')
                                    connector = charge_session.get('connector_id', 'N/A')
                                    end_time = charge_session.get('end_time')
                                    end_soc = charge_session.get('end_soc')
                                    
                                    if charger != 'N/A' and connector != 'N/A' and end_time:
                                        # Find Telexstraat point info from world
                                        telexstraat_point_name = "Garage Telexstraat"
                                        telexstraat_point_id = "30002"
                                        if world:
                                            # Try to find Telexstraat location
                                            for loc_id, location_obj in world.locations.items():
                                                if loc_id == 'Telexstraat' and hasattr(location_obj, 'point_id'):
                                                    telexstraat_point_id = str(location_obj.point_id)
                                                    if hasattr(location_obj, 'name'):
                                                        telexstraat_point_name = location_obj.name
                                                    break
                                        
                                        charge_start_str = datetime.fromtimestamp(charge_start_time).strftime('%Y-%m-%d %H:%M:%S')
                                        charge_end_str = datetime.fromtimestamp(end_time).strftime('%Y-%m-%d %H:%M:%S')
                                        end_soc_str = f"{end_soc:.2f}" if end_soc is not None and isinstance(end_soc, (int, float)) else "-"
                                        
                                        html_rows.append(f"""
        <tr class="point-row hidden indent-2" data-parent-id="journey-{journey_id_safe}" style="background-color: #fff3e0;">
            <td>{telexstraat_point_name} ({telexstraat_point_id})</td>
            <td>0.00</td>
            <td>{charge_start_str}</td>
            <td>{charge_end_str}</td>
            <td>{original_block_bus}</td>
            <td>{end_soc_str}</td>
            <td>{charger}-{connector}</td>
        </tr>""")
                                        break  # Only show first charging session
    
    return "\n".join(html_rows)


def generate_laadinfra_detailed_section(
    laadinfra_log: List[Dict[str, Any]],
    locations: Dict[str, Any],
    planning_log: Optional[List[Dict[str, Any]]] = None,
    telexstraat_hourly_limits_kw: Optional[List[float]] = None,
) -> str:
    """Generate laadinfra detailed report section from laadinfra_log."""
    # #region agent log
    # Debug: Count charging events
    try:
        debug_log_path = ".cursor/debug.log"
        charging_started_count = len([log for log in laadinfra_log if log.get('event') == 'charging_started'])
        charging_stopped_count = len([log for log in laadinfra_log if log.get('event') == 'charging_stopped'])
        charging_progress_count = len([log for log in laadinfra_log if log.get('event') == 'charging_progress'])
        with open(debug_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "sessionId": "debug-session",
                "runId": "report-gen",
                "hypothesisId": "H2",
                "location": "classified_report_generator.py:1583",
                "message": "Charging events count in laadinfra_log",
                "data": {
                    "charging_started_count": charging_started_count,
                    "charging_stopped_count": charging_stopped_count,
                    "charging_progress_count": charging_progress_count,
                    "total_events": len(laadinfra_log)
                },
                "timestamp": datetime.now().timestamp() * 1000
            }) + "\n")
    except Exception as e:
        pass
    # #endregion
    # Build power timeline for each location from per-bus power aggregation.
    # Rationale: `location_total_power_kw` in logs can lag/under-report when
    # multiple charging loops write in the same timestamp. Aggregating `power_kw`
    # by (location_id, time) gives the true location total for charting.
    location_time_power_sum: dict[str, dict[float, float]] = {}
    location_time_active_buses: dict[str, dict[float, set[str]]] = {}
    for log in laadinfra_log:
        if log.get('event') != 'charging_progress':
            continue
        location_id = log.get('location_id')
        time = log.get('time')
        power_kw = log.get('power_kw')
        bus_vin = log.get('bus_vin')
        if not location_id or time is None or power_kw is None:
            continue
        if location_id not in location_time_power_sum:
            location_time_power_sum[location_id] = {}
        if location_id not in location_time_active_buses:
            location_time_active_buses[location_id] = {}
        location_time_power_sum[location_id][float(time)] = (
            location_time_power_sum[location_id].get(float(time), 0.0) + float(power_kw)
        )
        if float(time) not in location_time_active_buses[location_id]:
            location_time_active_buses[location_id][float(time)] = set()
        if bus_vin and float(power_kw) > 0.001:
            location_time_active_buses[location_id][float(time)].add(str(bus_vin))

    location_power_timeline = {
        loc_id: sorted([(t, p) for t, p in time_map.items()], key=lambda x: x[0])
        for loc_id, time_map in location_time_power_sum.items()
    }
    # Build a map of journey_start events to help close charging sessions
    # Format: {bus_vin: {time: True}} for journey_start events
    journey_starts = {}
    if planning_log:
        for log in planning_log:
            if log.get('event') == 'journey_start':
                bus_vin = log.get('bus_vin')
                if bus_vin:
                    if bus_vin not in journey_starts:
                        journey_starts[bus_vin] = []
                    journey_starts[bus_vin].append(log.get('time'))
        # Sort journey start times for each bus
        for bus_vin in journey_starts:
            journey_starts[bus_vin].sort()
    
    # Track charging sessions
    active_sessions = {}
    charging_sessions = []
    
    # Combine laadinfra_log and journey_start events, sort by time
    all_events = []
    for log in laadinfra_log:
        all_events.append(('laadinfra', log))
    
    # Add journey_start events as "charging_stopped" markers
    for bus_vin, start_times in journey_starts.items():
        for start_time in start_times:
            all_events.append(('journey_start', {
                'event': 'journey_start',
                'time': start_time,
                'bus_vin': bus_vin
            }))
    
    # Sort all events by time
    all_events.sort(key=lambda x: x[1].get('time', 0))
    
    for event_source, log in all_events:
        event_type = log.get('event')
        bus_vin = log.get('bus_vin')
        
        if event_type == 'charging_started' and bus_vin:
            # If there's an existing session for this bus, check if it's a duplicate
            # Duplicate charging_started events (same time, same connector) should be ignored
            if bus_vin in active_sessions:
                existing_session = active_sessions[bus_vin]
                new_start_time = log.get('time')
                new_connector_id = log.get('connector_id')
                existing_connector_id = existing_session.get('connector_id')
                
                # Check if this is a duplicate charging_started event
                # (same time, same connector, same location)
                is_duplicate = (
                    abs(new_start_time - existing_session['start_time']) < 1.0 and  # Within 1 second
                    new_connector_id == existing_connector_id and
                    log.get('location_id') == existing_session.get('location_id')
                )
                
                if is_duplicate:
                    # This is a duplicate charging_started event, ignore it
                    # Don't close the existing session, just skip this event
                    continue
                
                # This is a new charging session (different connector or different time)
                # Close the existing session first
                session = existing_session
                # Use the last progress time or start time as end time
                end_time = session.get('last_progress_time', session['start_time'])
                
                # Only add to charging_sessions if the session had actual charging activity
                # (had progress events or charging actually occurred)
                had_progress = session.get('last_progress_time', session['start_time']) > session['start_time'] + 1.0
                had_power = session.get('had_power', False)
                
                if had_progress or had_power:
                    # Session had actual charging activity, add it to charging_sessions
                    charging_sessions.append({
                        'location_id': session['location_id'],
                        'charger_id': session['charger_id'],
                        'connector_id': session['connector_id'],
                        'bus_number': session['bus_number'],
                        'start_time': session['start_time'],
                        'end_time': end_time,
                        'start_soc': session['start_soc'],
                        'end_soc': session.get('current_soc', session['start_soc']),
                        'target_soc': session.get('target_soc'),
                        'strategy': session['strategy']
                    })
                # Remove the existing session regardless of whether we added it
                del active_sessions[bus_vin]
            
            # Start new session
            active_sessions[bus_vin] = {
                'location_id': log.get('location_id'),
                'charger_id': log.get('charger_id'),
                'connector_id': log.get('connector_id'),
                'bus_number': log.get('bus_number'),
                'start_time': log.get('time'),
                'start_soc': log.get('soc_percent', 0.0),
                'current_soc': log.get('soc_percent', 0.0),  # Initialize current_soc to start_soc
                'target_soc': log.get('target_soc'),  # Get target_soc from charging_started event
                'strategy': log.get('strategy_name') or log.get('strategy', 'N/A'),  # Prefer strategy_name, fallback to strategy
                'power_kw': 0.0,  # Initialize power_kw to 0
                'last_progress_time': log.get('time'),  # Track last progress time
                'had_power': False  # Track if we ever had power > 0 during this session
            }
        elif event_type == 'charging_progress' and bus_vin in active_sessions:
            # Update session with latest SOC and track progress time
            power_kw = log.get('power_kw', 0.0)
            if power_kw > 0:
                # Only update SOC if we're actually charging (power > 0)
                active_sessions[bus_vin]['current_soc'] = log.get('soc_percent', 0.0)
                active_sessions[bus_vin]['had_power'] = True  # Mark that we had power at some point
            # Always update power_kw and last_progress_time to track charging state
            active_sessions[bus_vin]['power_kw'] = power_kw
            active_sessions[bus_vin]['last_progress_time'] = log.get('time')  # Update last progress time
        elif event_type == 'charging_stopped' and bus_vin in active_sessions:
            # CRITICAL: Only use charging_stopped events to close charging sessions
            # This ensures we use the actual charging_stopped event, not journey_start events
            # which may belong to replacement buses or incorrect bus assignments
            session = active_sessions[bus_vin]
            end_time = log.get('time')
            
            # Use SOC from charging_stopped event if available, otherwise use current_soc from last progress
            end_soc = log.get('soc_percent')
            if end_soc is None:
                # Use the last known current_soc from charging_progress events
                end_soc = session.get('current_soc')
            if end_soc is None:
                # Fallback to start_soc if no progress was recorded
                end_soc = session['start_soc']
            
            # Check if charging actually occurred (power_kw > 0 at some point)
            # If power was always 0 (due to Grid limits), end_soc should equal start_soc
            had_power = session.get('had_power', False)
            if not had_power:
                # No actual charging occurred (power was always 0), end_soc should equal start_soc
                end_soc = session['start_soc']
            
            # Ensure end_soc is not less than start_soc (prevent reverse charging)
            # If end_soc < start_soc, use the last known current_soc or start_soc
            if end_soc < session['start_soc']:
                # Use the last known current_soc if available, otherwise keep start_soc
                end_soc = session.get('current_soc', session['start_soc'])
            
            charging_sessions.append({
                'location_id': session['location_id'],
                'charger_id': session['charger_id'],
                'connector_id': session['connector_id'],
                'bus_number': session['bus_number'],
                'start_time': session['start_time'],
                'end_time': end_time,
                'start_soc': session['start_soc'],
                'end_soc': end_soc,
                'target_soc': session.get('target_soc'),
                'strategy': session['strategy']
            })
            del active_sessions[bus_vin]
        elif event_source == 'journey_start' and bus_vin in active_sessions:
            # CRITICAL: Only use journey_start events to close charging sessions if:
            # 1. There's no charging_stopped event for this session (fallback)
            # 2. The journey_start event is after the last charging_progress event
            # 3. The bus is not in a journey_replacement scenario (bus was replaced)
            # 
            # However, we should prioritize charging_stopped events over journey_start events
            # because journey_start events may belong to replacement buses or incorrect assignments
            # 
            # For now, we'll skip journey_start events as charging_stopped markers
            # and rely on charging_stopped events or closing remaining sessions at the end
            # This prevents incorrect matching of journey_start events from replacement buses
            pass  # Skip journey_start events as charging_stopped markers
    
    # Close remaining active sessions
    # Use last_progress_time as end_time if available, otherwise use start_time
    # #region agent log
    remaining_sessions_count = len(active_sessions)
    # #endregion
    for bus_vin, session in active_sessions.items():
        end_time = session.get('last_progress_time', session['start_time'])
        # Use current_soc if available, otherwise use start_soc
        # Check if charging actually occurred (power_kw > 0 at some point)
        had_power = session.get('had_power', False)
        if not had_power:
            # No actual charging occurred (power was always 0), end_soc should equal start_soc
            end_soc = session['start_soc']
        else:
            end_soc = session.get('current_soc', session['start_soc'])
        # Ensure end_soc is not less than start_soc (prevent reverse charging)
        if end_soc < session['start_soc']:
            end_soc = session['start_soc']  # Prevent reverse charging
        
        charging_sessions.append({
            'location_id': session['location_id'],
            'charger_id': session['charger_id'],
            'connector_id': session['connector_id'],
            'bus_number': session['bus_number'],
            'start_time': session['start_time'],
            'end_time': end_time,
            'start_soc': session['start_soc'],
            'end_soc': end_soc,
            'target_soc': session.get('target_soc'),
            'strategy': session['strategy']
        })
    
    # #region agent log
    # Debug: Log charging sessions statistics, especially Telexstraat
    try:
        debug_log_path = ".cursor/debug.log"
        unique_locations = set()
        unique_connectors = set()
        telexstraat_sessions = []
        for session in charging_sessions:
            location_id = session.get('location_id')
            if location_id and location_id != 'N/A':
                unique_locations.add(location_id)
                if location_id == 'Telexstraat' or (isinstance(location_id, str) and 'Telexstraat' in location_id):
                    telexstraat_sessions.append({
                        'bus_number': session.get('bus_number'),
                        'start_time': session.get('start_time'),
                        'end_time': session.get('end_time'),
                        'charger_id': session.get('charger_id'),
                        'connector_id': session.get('connector_id')
                    })
            if session.get('connector_id') and session['connector_id'] != 'N/A':
                unique_connectors.add(session['connector_id'])
        with open(debug_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "sessionId": "debug-session",
                "runId": "report-gen",
                "hypothesisId": "H4",
                "location": "classified_report_generator.py:1795",
                "message": "Charging sessions statistics for LaadInfra report",
                "data": {
                    "total_sessions": len(charging_sessions),
                    "telexstraat_sessions_count": len(telexstraat_sessions),
                    "remaining_sessions_closed": remaining_sessions_count,
                    "unique_locations": len(unique_locations),
                    "unique_connectors": len(unique_connectors),
                    "locations": sorted(list(unique_locations)),
                    "telexstraat_sample": telexstraat_sessions[:10] if telexstraat_sessions else []
                },
                "timestamp": datetime.now().timestamp() * 1000
            }) + "\n")
    except Exception as e:
        pass
    # #endregion
    
    # Remove duplicate sessions (same bus_number, location_id, connector_id, start_time)
    # Use a set to track unique sessions
    seen_sessions = set()
    unique_sessions = []
    for session in charging_sessions:
        # Create a unique key for this session
        session_key = (
            session['bus_number'],
            session['location_id'],
            session['charger_id'],
            session['connector_id'],
            session['start_time']
        )
        if session_key not in seen_sessions:
            seen_sessions.add(session_key)
            unique_sessions.append(session)
    
    # Group by Location -> Charger -> Connector
    # IMPORTANT: Include ALL sessions, even if location_id is 'N/A' or charger/connector are 'N/A'
    # This ensures we don't lose charging records
    sessions_by_location = {}
    for session in unique_sessions:
        loc_id = session.get('location_id')
        # If location_id is missing or 'N/A', use a placeholder but still include the session
        if not loc_id or loc_id == 'N/A':
            # Try to infer location from charger_id or connector_id if possible
            charger_id = session.get('charger_id', 'N/A')
            connector_id = session.get('connector_id', 'N/A')
            # If we have charger_id or connector_id, try to find the location
            if charger_id != 'N/A' or connector_id != 'N/A':
                # Try to find location from existing sessions or locations dict
                # For now, use 'Unknown Location' as placeholder
                loc_id = 'Unknown Location'
            else:
                loc_id = 'Unknown Location'
        
        charger_id = session.get('charger_id') or 'Unknown'
        connector_id = session.get('connector_id') or 'Unknown'
        
        if loc_id not in sessions_by_location:
            sessions_by_location[loc_id] = {}
        if charger_id not in sessions_by_location[loc_id]:
            sessions_by_location[loc_id][charger_id] = {}
        if connector_id not in sessions_by_location[loc_id][charger_id]:
            sessions_by_location[loc_id][charger_id][connector_id] = []
        
        sessions_by_location[loc_id][charger_id][connector_id].append(session)
    
    # Sort all sessions by start_time (earliest first)
    for loc_id in sessions_by_location:
        for charger_id in sessions_by_location[loc_id]:
            for connector_id in sessions_by_location[loc_id][charger_id]:
                sessions_by_location[loc_id][charger_id][connector_id].sort(
                    key=lambda s: s['start_time'] if s['start_time'] is not None else float('inf')
                )
    
    # Generate HTML (similar to existing generate_laadinfra_detailed_report)
    html_parts = []
    
    # Add Chart.js library
    html_parts.append("""
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    """)
    
    # Add overall power comparison chart (showing top 4 locations)
    if location_power_timeline:
        # Get top 4 locations by number of data points
        sorted_locations = sorted(
            location_power_timeline.items(),
            key=lambda x: len(x[1]),
            reverse=True
        )[:4]
        
        if sorted_locations:
            # Find common time range
            all_times = set()
            for _, power_data in sorted_locations:
                for time, _ in power_data:
                    all_times.add(time)
            all_times = sorted(all_times)
            
            # Prepare datasets for each location
            datasets = []
            colors = [
                {'border': 'rgb(75, 192, 192)', 'bg': 'rgba(75, 192, 192, 0.2)'},
                {'border': 'rgb(255, 99, 132)', 'bg': 'rgba(255, 99, 132, 0.2)'},
                {'border': 'rgb(54, 162, 235)', 'bg': 'rgba(54, 162, 235, 0.2)'},
                {'border': 'rgb(255, 206, 86)', 'bg': 'rgba(255, 206, 86, 0.2)'}
            ]
            
            for idx, (loc_id, power_data) in enumerate(sorted_locations):
                # Create a map of time -> power for this location
                power_map = {time: power for time, power in power_data}
                # Interpolate power values for all times
                power_values = []
                last_power = 0.0
                for time in all_times:
                    if time in power_map:
                        last_power = power_map[time]
                    power_values.append(last_power)
                
                datasets.append({
                    'label': f'{loc_id} Total Power (kW)',
                    'data': power_values,
                    'borderColor': colors[idx % len(colors)]['border'],
                    'backgroundColor': colors[idx % len(colors)]['bg'],
                    'tension': 0.1,
                    'fill': False
                })
            
            times_str = [datetime.fromtimestamp(t).strftime('%Y-%m-%d %H:%M:%S') for t in all_times]
            
            html_parts.append("""
            <div style="margin: 20px 0; padding: 20px; background-color: #fff; border: 1px solid #dee2e6; border-radius: 4px;">
                <h3 style="margin-bottom: 15px;">Location Power Comparison (Top 4 Locations)</h3>
                <canvas id="location-power-comparison-chart" style="max-height: 500px;"></canvas>
                <script>
                    (function() {
                        const ctx = document.getElementById('location-power-comparison-chart');
                        if (ctx && typeof Chart !== 'undefined') {
                            new Chart(ctx, {
                                type: 'line',
                                data: {
                                    labels: """ + json.dumps(times_str) + """,
                                    datasets: """ + json.dumps(datasets) + """
                                },
                                options: {
                                    responsive: true,
                                    maintainAspectRatio: true,
                                    scales: {
                                        y: {
                                            beginAtZero: true,
                                            title: {
                                                display: true,
                                                text: 'Power (kW)'
                                            }
                                        },
                                        x: {
                                            title: {
                                                display: true,
                                                text: 'Time'
                                            },
                                            ticks: {
                                                maxRotation: 45,
                                                minRotation: 45
                                            }
                                        }
                                    },
                                    plugins: {
                                        legend: {
                                            display: true,
                                            position: 'top'
                                        },
                                        tooltip: {
                                            mode: 'index',
                                            intersect: false
                                        }
                                    }
                                }
                            });
                        }
                    })();
                </script>
            </div>
            """)
    
    # Show all locations (both from locations dict AND from sessions_by_location)
    # This ensures we show all charging locations, even if they're not in the locations dict
    all_location_ids = set(locations.keys())
    # Also include locations from sessions_by_location that might not be in locations dict
    for loc_id in sessions_by_location.keys():
        if loc_id and loc_id != 'N/A':
            all_location_ids.add(loc_id)
    
    for loc_id in sorted(all_location_ids):
        # Get location from dict if available, otherwise create a minimal location object
        location = locations.get(loc_id)
        if location is None:
            # Create a minimal location object for locations not in the dict
            from types import SimpleNamespace
            location = SimpleNamespace(
                point_id=None,
                chargers={}
            )
        
        loc_safe_id = loc_id.replace(':', '-').replace('/', '-').replace(' ', '-')
        
        total_sessions = 0
        if loc_id in sessions_by_location:
            total_sessions = sum(
                len(sessions)
                for charger_dict in sessions_by_location[loc_id].values()
                for connector_sessions in charger_dict.values()
                for sessions in [connector_sessions]
            )
        
        session_text = "s" if total_sessions != 1 else ""
        location_header_text = f"Location: {loc_id}"
        if location.point_id:
            location_header_text += f" (Point ID: {location.point_id})"
        
        html_parts.append(f"""
        <div class="location-section">
            <div class="location-header collapsed" id="loc-header-{loc_safe_id}" onclick="toggleLocation('{loc_safe_id}')">
                <span class="toggle-icon">▶</span>
                <strong>{location_header_text}</strong>
                <span class="session-count">({total_sessions} charging session{session_text})</span>
            </div>
            <div class="location-content hidden" id="loc-content-{loc_safe_id}">
        """)
        
        # Add power_kw over time chart for this location
        if loc_id in location_power_timeline and location_power_timeline[loc_id]:
            power_data = location_power_timeline[loc_id]
            # Prepare data for Chart.js
            time_points = [t for t, _ in power_data]
            times = [datetime.fromtimestamp(t).strftime('%Y-%m-%d %H:%M:%S') for t in time_points]
            powers = [p for _, p in power_data]
            # Compute active charging buses at each time point for this location.
            # A bus counts only when charging power > 0 at that timestamp.
            active_by_time = location_time_active_buses.get(loc_id, {})
            charging_bus_counts: List[int] = []
            for ts in time_points:
                charging_bus_counts.append(len(active_by_time.get(ts, set())))

            # Optional: compute limit line for Telexstraat using provided hourly limits
            telexstraat_limits_values = None
            if (
                loc_id == "Telexstraat"
                and telexstraat_hourly_limits_kw
                and isinstance(telexstraat_hourly_limits_kw, list)
            ):
                telexstraat_limits_values = []
                for t, _ in power_data:
                    dt = datetime.fromtimestamp(t)
                    h = dt.hour
                    if 0 <= h < len(telexstraat_hourly_limits_kw):
                        telexstraat_limits_values.append(telexstraat_hourly_limits_kw[h])
                    else:
                        telexstraat_limits_values.append(None)

            # Build datasets for Chart.js
            location_datasets: List[Dict[str, Any]] = [
                {
                    "label": f"{loc_id} Total Power (kW)",
                    "data": powers,
                    "borderColor": "rgb(75, 192, 192)",
                    "backgroundColor": "rgba(75, 192, 192, 0.2)",
                    "tension": 0.1,
                    "fill": True,
                    "yAxisID": "y",
                },
                {
                    "label": "Active Charging Buses (power>0)",
                    "data": charging_bus_counts,
                    "borderColor": "rgb(255, 99, 132)",
                    "backgroundColor": "rgba(255, 99, 132, 0.15)",
                    "tension": 0.1,
                    "fill": False,
                    "yAxisID": "y1",
                }
            ]
            if telexstraat_limits_values is not None:
                location_datasets.append(
                    {
                        "label": "Telexstraat Limit (kW)",
                        "data": telexstraat_limits_values,
                        "borderColor": "rgba(220, 53, 69, 0.9)",
                        "borderDash": [5, 5],
                        "pointRadius": 0,
                        "fill": False,
                        "yAxisID": "y",
                    }
                )

            chart_id = f"power-chart-{loc_safe_id}"
            html_parts.append(f"""
                <div style="margin: 20px 0; padding: 15px; background-color: #f8f9fa; border: 1px solid #dee2e6; border-radius: 4px;">
                    <h4 style="margin-bottom: 10px;">Location Total Power Over Time</h4>
                    <canvas id="{chart_id}" style="max-height: 400px;"></canvas>
                    <script>
                        (function() {{
                            const ctx = document.getElementById('{chart_id}');
                            if (ctx && typeof Chart !== 'undefined') {{
                                new Chart(ctx, {{
                                    type: 'line',
                                    data: {{
                                        labels: {json.dumps(times)},
                                        datasets: {json.dumps(location_datasets)}
                                    }},
                                    options: {{
                                        responsive: true,
                                        maintainAspectRatio: true,
                                        scales: {{
                                            y: {{
                                                beginAtZero: true,
                                                title: {{
                                                    display: true,
                                                    text: 'Power (kW)'
                                                }}
                                            }},
                                            y1: {{
                                                beginAtZero: true,
                                                position: 'right',
                                                grid: {{
                                                    drawOnChartArea: false
                                                }},
                                                title: {{
                                                    display: true,
                                                    text: 'Charging Buses'
                                                }},
                                                ticks: {{
                                                    precision: 0
                                                }}
                                            }},
                                            x: {{
                                                title: {{
                                                    display: true,
                                                    text: 'Time'
                                                }},
                                                ticks: {{
                                                    maxRotation: 45,
                                                    minRotation: 45
                                                }}
                                            }}
                                        }},
                                        plugins: {{
                                            legend: {{
                                                display: true,
                                                position: 'top'
                                            }},
                                            tooltip: {{
                                                mode: 'index',
                                                intersect: false
                                            }}
                                        }}
                                    }}
                                }});
                            }}
                        }})();
                    </script>
                </div>
            """)
        
        if loc_id in sessions_by_location and sessions_by_location[loc_id]:
            for charger_id in sorted(sessions_by_location[loc_id].keys()):
                charger_safe_id = f"{loc_safe_id}-{charger_id.replace(':', '-').replace('/', '-').replace(' ', '-')}"
                charger = location.chargers.get(charger_id)
                charger_name = charger_id if charger_id != 'Unknown' else f"Charger {charger_id}"
                
                charger_sessions = sum(
                    len(sessions)
                    for connector_sessions in sessions_by_location[loc_id][charger_id].values()
                    for sessions in [connector_sessions]
                )
                charger_session_text = "s" if charger_sessions != 1 else ""
                
                html_parts.append(f"""
                <div class="charger-section">
                    <div class="charger-header collapsed" id="charger-header-{charger_safe_id}" onclick="toggleCharger('{charger_safe_id}')">
                        <span class="toggle-icon">▶</span>
                        <strong>Charger: {charger_name}</strong>
                        <span class="session-count">({charger_sessions} session{charger_session_text})</span>
                    </div>
                    <div class="charger-content hidden" id="charger-content-{charger_safe_id}">
                """)
                
                for connector_id in sorted(sessions_by_location[loc_id][charger_id].keys()):
                    connector_sessions = sessions_by_location[loc_id][charger_id][connector_id]
                    connector_safe_id = f"{charger_safe_id}-{connector_id.replace(':', '-').replace('/', '-').replace(' ', '-')}"
                    
                    connector_name = connector_id
                    if charger and connector_id != 'Unknown':
                        for conn in charger.connectors:
                            if conn.connector_id == connector_id:
                                connector_name = f"{connector_id} ({conn.max_power_kw}kW)"
                                break
                    elif connector_id == 'Unknown':
                        connector_name = "Unknown Connector"
                    
                    html_parts.append(f"""
                    <div class="connector-section">
                        <div class="connector-header collapsed" id="connector-header-{connector_safe_id}" onclick="toggleConnector('{connector_safe_id}')">
                            <span class="toggle-icon">▶</span>
                            <strong>Connector: {connector_name}</strong>
                            <span class="session-count">({len(connector_sessions)} session{"s" if len(connector_sessions) != 1 else ""})</span>
                        </div>
                        <div class="connector-content hidden" id="connector-content-{connector_safe_id}">
                            <table>
                                <thead>
                                    <tr>
                                        <th>Bus Number</th>
                                        <th>Start Time</th>
                                        <th>End Time</th>
                                        <th>Start SOC (%)</th>
                                        <th>End SOC (%)</th>
                                        <th>Target SOC (%)</th>
                                        <th>Strategy</th>
                                    </tr>
                                </thead>
                                <tbody>
                    """)
                    
                    connector_sessions.sort(key=lambda s: s['start_time'])
                    for session in connector_sessions:
                        start_time_str = datetime.fromtimestamp(session['start_time']).strftime('%Y-%m-%d %H:%M:%S') if session['start_time'] else "N/A"
                        end_time_str = datetime.fromtimestamp(session['end_time']).strftime('%Y-%m-%d %H:%M:%S') if session['end_time'] else "N/A"
                        target_soc_str = f"{session['target_soc']:.1f}" if session['target_soc'] is not None else "Until next journey"
                        
                        html_parts.append(f"""
                                    <tr>
                                        <td>{session['bus_number']}</td>
                                        <td>{start_time_str}</td>
                                        <td>{end_time_str}</td>
                                        <td>{session['start_soc']:.2f}</td>
                                        <td>{session['end_soc']:.2f}</td>
                                        <td>{target_soc_str}</td>
                                        <td>{session['strategy']}</td>
                                    </tr>
                        """)
                    
                    html_parts.append("""
                                </tbody>
                            </table>
                        </div>
                    </div>
                    """)
                
                html_parts.append("""
                    </div>
                </div>
                """)
        else:
            html_parts.append("""
                <p style="color: #6c757d; font-style: italic; padding: 10px;">
                    No charging sessions recorded for this location.
                </p>
            """)
        
        html_parts.append("""
            </div>
        </div>
        """)
    
    return "\n".join(html_parts)


def generate_replay_map_from_classified_logs(
    sim: "SecondBasedSimulationEngine",
    output_path: str,
    locations: Optional[Dict[str, Any]] = None,
):
    """Generate replay map from classified logs."""
    # Use bus_log and planning_log to reconstruct bus movements
    replay_data = []
    
    # Get world for point lookup
    world = getattr(sim, 'world', None)
    
    # Combine bus_log and planning_log for complete picture
    all_logs = []
    all_logs.extend(sim.classified_logger.bus_log)
    all_logs.extend(sim.classified_logger.planning_log)
    
    sorted_logs = sorted(all_logs, key=lambda x: x.get('time', 0))
    
    for log in sorted_logs:
        event_type = log.get('event')
        location = log.get('location')
        
        # For planning_log point_arrival events, we need to look up point coordinates
        if event_type == 'point_arrival' and not location:
            point_id = log.get('point_id')
            journey_id = log.get('journey_id')
            if point_id and journey_id and world:
                # Find point in world
                for block in world.blocks.values():
                    for journey in block.journeys:
                        if journey.journey_id == journey_id:
                            for point in journey.points:
                                if str(point.point_id) == str(point_id):
                                    location = {
                                        'latitude': point.latitude,
                                        'longitude': point.longitude,
                                        'name': point.name,
                                        'point_id': point.point_id
                                    }
                                    break
                            if location:
                                break
                    if location:
                        break
        
        if location and location.get('latitude') and location.get('longitude'):
            time_str = datetime.fromtimestamp(log['time']).strftime('%Y-%m-%d %H:%M:%S')
            
            # Determine state
            state = log.get('state', 'IDLE')
            if isinstance(state, str):
                if state == 'CHARGING':
                    state = 'CHARGING'
                elif state in ['RUNNING', 'IN_SERVICE', 'ON_ROUTE']:
                    state = 'RUNNING'
                else:
                    state = 'IDLE'
            elif event_type == 'point_arrival':
                # If it's a point_arrival event, bus is running
                state = 'RUNNING'
            
            replay_data.append({
                "time": time_str,
                "time_ts": log['time'],
                "lat": location['latitude'],
                "lng": location['longitude'],
                "bus_id": str(log.get('bus_number', log.get('bus_vin', 'N/A'))),
                "line_nr": "N/A",
                "journey_id": log.get('journey_id', 'N/A'),
                "point_name": location.get('name', f"Point {location.get('point_id', 'N/A')}"),
                "soc": f"{log.get('soc_percent', 0.0):.2f}",
                "state": state
            })
    
    # Load template and inject data
    template_path = Path(__file__).parent / "templates" / "replay_map_template.html"
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            template_html = f.read()
    except FileNotFoundError:
        print(f"[WARNING] Template replay_map_template.html not found.")
        return
    
    # Collect final positions of all buses at simulation end
    final_positions = []
    if world:
        sim_end_time = getattr(sim, 'current_time', None)
        for bus in world.buses:
            final_pos = {
                "bus_id": str(bus.vehicle_number),
                "bus_vin": bus.vin_number,
                "state": bus.state.value if hasattr(bus.state, 'value') else str(bus.state),
                "soc": bus.soc_percent,
                "time_ts": sim_end_time,
                "is_final_position": True  # Mark as final position
            }
            
            # Get location from bus
            if bus.location:
                final_pos["lat"] = bus.location.latitude
                final_pos["lng"] = bus.location.longitude
                final_pos["point_name"] = bus.location.name
                final_pos["point_id"] = str(bus.location.point_id)
            else:
                # If no location, try to get from last log entry
                last_log = None
                for log in sorted(sim.classified_logger.bus_log + sim.classified_logger.planning_log, 
                                 key=lambda x: x.get('time', 0), reverse=True):
                    if (log.get('bus_number') == bus.vehicle_number or 
                        log.get('bus_vin') == bus.vin_number):
                        location = log.get('location')
                        if location and location.get('latitude') and location.get('longitude'):
                            final_pos["lat"] = location['latitude']
                            final_pos["lng"] = location['longitude']
                            final_pos["point_name"] = location.get('name', 'Unknown')
                            final_pos["point_id"] = str(location.get('point_id', 'N/A'))
                            break
                
                # If still no location found, skip this bus
                if "lat" not in final_pos:
                    continue
            
            final_positions.append(final_pos)
    
    replay_data_json = json.dumps(replay_data, ensure_ascii=False)
    final_positions_json = json.dumps(final_positions, ensure_ascii=False)
    final_html = template_html.replace("{{ REPLAY_DATA }}", replay_data_json)
    final_html = final_html.replace("{{ FINAL_POSITIONS }}", final_positions_json)
    final_html = final_html.replace("{{ LOCATION_DATA }}", json.dumps([]))
    final_html = final_html.replace("{{ SNAPSHOT_LOCATION_DATA }}", json.dumps({}))
    
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(final_html)
    
    print(f"Replay map generated: {output_path}")
    if final_positions:
        print(f"  - Added {len(final_positions)} final bus positions")