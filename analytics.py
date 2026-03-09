"""
CPAP/BiPAP Analytics - Therapy Report System
Version 2.0 - Complete with mode-specific reporting and accurate calculations
"""

import os
import pandas as pd
import numpy as np
import math
from datetime import datetime, timedelta
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
import matplotlib.pyplot as plt
import sys
from collections import Counter, defaultdict
import random
import json
import csv
import base64
from io import BytesIO
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
import warnings
import subprocess
warnings.filterwarnings('ignore')


class PressureCalculator:
    """Pressure calculation logic for CPAP/BiPAP devices based on PHP code"""
    
    @staticmethod
    def calculate_pressure(max_pressure, min_pressure, pressure_change_count, mode):
        """Calculate pressure metrics based on device mode - exact PHP logic"""
        try:
            max_pressure = float(max_pressure)
            min_pressure = float(min_pressure)
            pressure_change_count = int(pressure_change_count)
            
            # Auto modes use formula, manual modes use set pressure
            mode_str = str(mode).strip()
            
            # Manual modes (1,01,3,03,5,05) - use set pressure
            if mode_str in ['1', '01', '3', '03', '5', '05']:
                calculated_max = min_pressure if min_pressure > 0 else max_pressure
                median = 0
                percentile_95 = calculated_max
                rounded_max = round(calculated_max)
                is_manual = True
                
            else:
                # Auto modes - calculate based on pressure changes
                calculated_max = min_pressure + (pressure_change_count / 10.0)
                
                # Cap at maximum pressure if exceeded
                if calculated_max >= max_pressure:
                    calculated_max = max_pressure
                
                percentile_95 = calculated_max * 0.95
                
                # Calculate median from pressure range
                rounded_max = round(calculated_max)
                
                median = 0
                if min_pressure <= rounded_max:
                    pressure_range = list(range(int(min_pressure), int(rounded_max) + 1))
                else:
                    pressure_range = list(range(int(rounded_max), int(min_pressure) + 1))
                
                if len(pressure_range) > 0:
                    pressure_range.sort(reverse=True)
                    array_size = len(pressure_range)
                    middle_index = array_size / 2
                    
                    if array_size % 2 != 0:
                        median = pressure_range[int(middle_index)]
                    else:
                        median1 = pressure_range[int(middle_index)]
                        median2 = pressure_range[int(middle_index) - 1]
                        median = (median1 + median2) / 2
                
                is_manual = False
            
            return {
                'calculated_max': round(calculated_max, 1),
                'rounded_max': rounded_max,
                'median': round(median, 1),
                'percentile_95': round(percentile_95, 1),
                'pressure_change_count': pressure_change_count,
                'min_pressure': min_pressure,
                'max_pressure': max_pressure,
                'is_manual_mode': is_manual
            }
            
        except Exception as e:
            print(f"Pressure calculation error: {e}")
            return {
                'calculated_max': 0.0,
                'rounded_max': 0,
                'median': 0.0,
                'percentile_95': 0.0,
                'pressure_change_count': 0,
                'min_pressure': 0.0,
                'max_pressure': 0.0,
                'is_manual_mode': False
            }

    @staticmethod
    def calculate_event_indices(central_count, obstructive_count, hypopnea_count, usage_minutes, mode):
        """Calculate event indices (AHI, AI, HI) - exact PHP logic"""
        try:
            mode_str = str(mode).strip()
            
            # Special case for certain modes with zero events - PHP logic: if (($CSA == 0 && $OSA == 0 && $HSA == 0) && ($mode == "3" || $mode == "03" || $mode == "5" || $mode == "05")) { $HSA = 1; }
            if (central_count == 0 and obstructive_count == 0 and hypopnea_count == 0 and 
                mode_str in ['3', '03', '5', '05']):
                hypopnea_count = 1
            
            usage_hours = usage_minutes / 60.0
            
            if usage_hours > 0:
                central_index = central_count / usage_hours
                obstructive_index = obstructive_count / usage_hours
                hypopnea_index = hypopnea_count / usage_hours
                apnea_index = central_index + obstructive_index
                apnea_hypopnea_index = apnea_index + hypopnea_index
                
                return {
                    'central': round(central_index, 2),
                    'obstructive': round(obstructive_index, 2),
                    'hypopnea': round(hypopnea_index, 2),
                    'apnea': round(apnea_index, 2),
                    'ahi': round(apnea_hypopnea_index, 2),
                    'usage_hours': round(usage_hours, 1)
                }
            else:
                return {
                    'central': 0.0,
                    'obstructive': 0.0,
                    'hypopnea': 0.0,
                    'apnea': 0.0,
                    'ahi': 0.0,
                    'usage_hours': 0.0
                }
        except Exception as e:
            print(f"Event index calculation error: {e}")
            return {
                'central': 0.0, 'obstructive': 0.0, 'hypopnea': 0.0,
                'apnea': 0.0, 'ahi': 0.0, 'usage_hours': 0.0
            }

    @staticmethod
    def adjust_leak_value(raw_leak):
        """Adjust leak values for reporting - exact PHP logic"""
        try:
            leak = float(raw_leak)
            
            # Adjust unrealistic leak values - PHP logic
            if leak > 70:
                leak = 39 + random.randint(1, 9)
            elif leak == 0:
                leak = random.randint(5, 15)
            
            return round(leak, 2)
        except:
            return 0.0

    @staticmethod
    def calculate_95th_percentile(value, factor=0.83):
        """Calculate 95th percentile using fixed factor (as in PHP code)"""
        try:
            return float(value) * factor
        except:
            return 0.0


class DailyPressureAggregator:
    """Aggregate daily pressure and event data - handles multiple sessions per day"""
    
    def __init__(self):
        self.reset_counters()
    
    def reset_counters(self):
        """Reset all daily counters"""
        self.total_max_pressure = 0.0
        self.total_median_pressure = 0.0
        self.total_percentile_95 = 0.0
        
        self.event_counts = {
            'central': 0,
            'obstructive': 0,
            'hypopnea': 0
        }
        
        self.pressure_settings = {
            'min_sum': 0.0,
            'max_sum': 0.0,
            'min_avg': 0.0,
            'max_avg': 0.0
        }
        
        # BiPAP metrics
        self.tidal_volume_sum = 0.0
        self.respiratory_rate_sum = 0.0
        self.minute_ventilation_sum = 0.0
        self.tidal_volume_95_sum = 0.0
        self.respiratory_rate_95_sum = 0.0
        self.minute_ventilation_95_sum = 0.0
        
        self.total_minutes = 0.0
        self.leak_values = []
        self.session_count = 1
        self.same_day_counter = 0
    
    def process_daily_pressure(self, session_data, is_last_session=False):
        """Process pressure data for a day"""
        try:
            mode = session_data.get('mode', '0')
            calculated_max = session_data.get('calculated_max', 0.0)
            median = session_data.get('median', 0.0)
            percentile_95 = session_data.get('percentile_95', 0.0)
            min_pressure = session_data.get('min_pressure', 0.0)
            max_pressure_setting = session_data.get('max_pressure_setting', 0.0)
            pressure_change_count = session_data.get('pressure_change_count', 0)
            
            central_count = session_data.get('central_count', 0)
            obstructive_count = session_data.get('obstructive_count', 0)
            hypopnea_count = session_data.get('hypopnea_count', 0)
            leak = session_data.get('leak', 0.0)
            duration_minutes = session_data.get('duration_minutes', 0.0)
            
            # BiPAP metrics
            tidal_volume = session_data.get('tidal_volume', 0.0)
            respiratory_rate = session_data.get('respiratory_rate', 0.0)
            minute_ventilation = session_data.get('minute_ventilation', 0.0)
            tidal_volume_95 = session_data.get('tidal_volume_95', 0.0)
            respiratory_rate_95 = session_data.get('respiratory_rate_95', 0.0)
            minute_ventilation_95 = session_data.get('minute_ventilation_95', 0.0)
            
            # Single reading per day
            if self.same_day_counter == 1:
                return self._process_single_reading(
                    calculated_max, median, percentile_95, min_pressure, 
                    max_pressure_setting, central_count, obstructive_count, 
                    hypopnea_count, leak, duration_minutes, mode,
                    tidal_volume, respiratory_rate, minute_ventilation,
                    tidal_volume_95, respiratory_rate_95, minute_ventilation_95
                )
            
            # Multiple readings per day
            elif self.same_day_counter > 1:
                return self._process_multiple_readings(
                    calculated_max, median, percentile_95, min_pressure, 
                    max_pressure_setting, central_count, obstructive_count, 
                    hypopnea_count, leak, duration_minutes, mode,
                    tidal_volume, respiratory_rate, minute_ventilation,
                    tidal_volume_95, respiratory_rate_95, minute_ventilation_95,
                    is_last_session
                )
            
            return None
            
        except Exception as e:
            print(f"Daily pressure processing error: {e}")
            return None
    
    def _process_single_reading(self, calculated_max, median, percentile_95, min_pressure,
                               max_pressure_setting, central_count, obstructive_count,
                               hypopnea_count, leak, duration_minutes, mode,
                               tidal_volume, respiratory_rate, minute_ventilation,
                               tidal_volume_95, respiratory_rate_95, minute_ventilation_95):
        """Process single reading per day"""
        event_data = PressureCalculator.calculate_event_indices(
            central_count, obstructive_count, hypopnea_count, duration_minutes, mode
        )
        
        daily_data = {
            'total_minutes': duration_minutes,
            'therapy_hours': event_data['usage_hours'],
            'max_pressure': round(calculated_max, 1),
            'median_pressure': round(median, 1),
            'percentile_95_pressure': round(percentile_95, 1),
            'graph_pressure': round(percentile_95, 1),
            'set_pressure': min_pressure if min_pressure > 0 else max_pressure_setting,
            'ahi_index': event_data['ahi'],
            'apnea_index': event_data['apnea'],
            'hypopnea_index': event_data['hypopnea'],
            'central_index': event_data['central'],
            'obstructive_index': event_data['obstructive'],
            'leak': round(leak, 2),
            'total_central': central_count,
            'total_obstructive': obstructive_count,
            'total_hypopnea': hypopnea_count,
            'min_pressure_setting': min_pressure,
            'max_pressure_setting': max_pressure_setting,
            'pressure_change_count': 0,
            'sessions_count': 1,
            
            # BiPAP metrics
            'tidal_volume': round(tidal_volume, 1),
            'respiratory_rate': round(respiratory_rate, 1),
            'minute_ventilation': round(minute_ventilation, 1),
            'tidal_volume_95': round(tidal_volume_95, 1),
            'respiratory_rate_95': round(respiratory_rate_95, 1),
            'minute_ventilation_95': round(minute_ventilation_95, 1),
            
            # IPAP/EPAP for BiPAP
            'ipap': round(max_pressure_setting, 1),
            'epap': round(min_pressure, 1)
        }
        
        return daily_data
    
    def _process_multiple_readings(self, calculated_max, median, percentile_95, min_pressure,
                                  max_pressure_setting, central_count, obstructive_count,
                                  hypopnea_count, leak, duration_minutes, mode,
                                  tidal_volume, respiratory_rate, minute_ventilation,
                                  tidal_volume_95, respiratory_rate_95, minute_ventilation_95,
                                  is_last_session):
        """Process multiple readings per day"""
        mode_str = str(mode).strip()
        self.total_minutes += duration_minutes
        
        # For auto modes, accumulate pressure values
        if mode_str not in ['1', '01', '3', '03', '5', '05']:
            self.total_max_pressure += calculated_max
            self.total_median_pressure += median
            self.total_percentile_95 += percentile_95
        else:
            # For manual modes, use set pressure
            self.total_max_pressure = min_pressure if min_pressure > 0 else max_pressure_setting
            self.total_median_pressure = 0
            self.total_percentile_95 = self.total_max_pressure
        
        self.leak_values.append(round(leak, 1))
        self.event_counts['central'] += central_count
        self.event_counts['obstructive'] += obstructive_count
        self.event_counts['hypopnea'] += hypopnea_count
        self.pressure_settings['min_sum'] += min_pressure
        self.pressure_settings['max_sum'] += max_pressure_setting
        
        # Accumulate BiPAP metrics
        self.tidal_volume_sum += tidal_volume
        self.respiratory_rate_sum += respiratory_rate
        self.minute_ventilation_sum += minute_ventilation
        self.tidal_volume_95_sum += tidal_volume_95
        self.respiratory_rate_95_sum += respiratory_rate_95
        self.minute_ventilation_95_sum += minute_ventilation_95
        
        if is_last_session:
            return self._finalize_daily_averages(mode)
        
        self.session_count += 1
        return None
    
    def _finalize_daily_averages(self, mode):
        """Calculate final daily averages"""
        mode_str = str(mode).strip()
        
        event_data = PressureCalculator.calculate_event_indices(
            self.event_counts['central'], 
            self.event_counts['obstructive'], 
            self.event_counts['hypopnea'],
            self.total_minutes, mode
        )
        
        if mode_str not in ['1', '01', '3', '03', '5', '05']:
            avg_max = self.total_max_pressure / self.same_day_counter
            avg_median = self.total_median_pressure / self.same_day_counter
            avg_percentile_95 = self.total_percentile_95 / self.same_day_counter
        else:
            avg_max = self.total_max_pressure
            avg_median = 0
            avg_percentile_95 = self.total_max_pressure
        
        self.pressure_settings['min_avg'] = self.pressure_settings['min_sum'] / self.same_day_counter
        self.pressure_settings['max_avg'] = self.pressure_settings['max_sum'] / self.same_day_counter
        
        max_leak = max(self.leak_values) if self.leak_values else 0
        
        # Average BiPAP metrics
        avg_tidal = self.tidal_volume_sum / self.same_day_counter if self.same_day_counter > 0 else 0
        avg_rr = self.respiratory_rate_sum / self.same_day_counter if self.same_day_counter > 0 else 0
        avg_mv = self.minute_ventilation_sum / self.same_day_counter if self.same_day_counter > 0 else 0
        avg_tidal_95 = self.tidal_volume_95_sum / self.same_day_counter if self.same_day_counter > 0 else 0
        avg_rr_95 = self.respiratory_rate_95_sum / self.same_day_counter if self.same_day_counter > 0 else 0
        avg_mv_95 = self.minute_ventilation_95_sum / self.same_day_counter if self.same_day_counter > 0 else 0
        
        daily_data = {
            'total_minutes': round(self.total_minutes, 1),
            'therapy_hours': event_data['usage_hours'],
            'max_pressure': round(avg_max, 1),
            'median_pressure': round(avg_median, 1),
            'percentile_95_pressure': round(avg_percentile_95, 1),
            'graph_pressure': round(avg_percentile_95, 1),
            'set_pressure': round(self.pressure_settings['min_avg'], 1),
            'ahi_index': event_data['ahi'],
            'apnea_index': event_data['apnea'],
            'hypopnea_index': event_data['hypopnea'],
            'central_index': event_data['central'],
            'obstructive_index': event_data['obstructive'],
            'leak': round(max_leak, 2),
            'total_central': self.event_counts['central'],
            'total_obstructive': self.event_counts['obstructive'],
            'total_hypopnea': self.event_counts['hypopnea'],
            'min_pressure_setting': round(self.pressure_settings['min_avg'], 1),
            'max_pressure_setting': round(self.pressure_settings['max_avg'], 1),
            'pressure_change_count': 0,
            'sessions_count': self.same_day_counter,
            
            # BiPAP metrics
            'tidal_volume': round(avg_tidal, 1),
            'respiratory_rate': round(avg_rr, 1),
            'minute_ventilation': round(avg_mv, 1),
            'tidal_volume_95': round(avg_tidal_95, 1),
            'respiratory_rate_95': round(avg_rr_95, 1),
            'minute_ventilation_95': round(avg_mv_95, 1),
            
            # IPAP/EPAP
            'ipap': round(self.pressure_settings['max_avg'], 1),
            'epap': round(self.pressure_settings['min_avg'], 1)
        }
        
        self.reset_counters()
        return daily_data


class OverallPressureMetrics:
    """Calculate overall pressure metrics across all days"""
    
    @staticmethod
    def calculate_overall_averages(daily_metrics):
        """Calculate overall averages from daily metrics"""
        if not daily_metrics:
            return {
                'avg_max': 0.0,
                'avg_median': 0.0,
                'avg_percentile_95': 0.0,
                'avg_set_pressure': 0.0,
                'avg_ahi': 0.0,
                'avg_apnea': 0.0,
                'avg_hypopnea': 0.0,
                'avg_leak': 0.0,
                'avg_central': 0.0,
                'avg_obstructive': 0.0,
                'total_days': 0,
                'total_minutes': 0,
                'total_hours': 0.0,
                'total_central': 0,
                'total_obstructive': 0,
                'total_hypopnea': 0,
                
                # BiPAP metrics
                'avg_tidal_volume': 0.0,
                'avg_respiratory_rate': 0.0,
                'avg_minute_ventilation': 0.0,
                'avg_tidal_volume_95': 0.0,
                'avg_respiratory_rate_95': 0.0,
                'avg_minute_ventilation_95': 0.0,
                'avg_ipap': 0.0,
                'avg_epap': 0.0
            }
        
        total_days = len(daily_metrics)
        
        total_max = sum(d['max_pressure'] for d in daily_metrics)
        total_median = sum(d['median_pressure'] for d in daily_metrics)
        total_percentile_95 = sum(d['percentile_95_pressure'] for d in daily_metrics)
        total_set_pressure = sum(d.get('set_pressure', 0) for d in daily_metrics)
        
        total_minutes = sum(d['total_minutes'] for d in daily_metrics)
        total_hours = sum(d['therapy_hours'] for d in daily_metrics)
        total_central = sum(d['total_central'] for d in daily_metrics)
        total_obstructive = sum(d['total_obstructive'] for d in daily_metrics)
        total_hypopnea = sum(d['total_hypopnea'] for d in daily_metrics)
        
        # BiPAP metrics sums
        total_tidal = sum(d.get('tidal_volume', 0) for d in daily_metrics)
        total_rr = sum(d.get('respiratory_rate', 0) for d in daily_metrics)
        total_mv = sum(d.get('minute_ventilation', 0) for d in daily_metrics)
        total_tidal_95 = sum(d.get('tidal_volume_95', 0) for d in daily_metrics)
        total_rr_95 = sum(d.get('respiratory_rate_95', 0) for d in daily_metrics)
        total_mv_95 = sum(d.get('minute_ventilation_95', 0) for d in daily_metrics)
        total_ipap = sum(d.get('ipap', 0) for d in daily_metrics)
        total_epap = sum(d.get('epap', 0) for d in daily_metrics)
        
        avg_max = total_max / total_days
        avg_median = total_median / total_days
        avg_percentile_95 = total_percentile_95 / total_days
        avg_set_pressure = total_set_pressure / total_days
        
        avg_ahi = sum(d['ahi_index'] for d in daily_metrics) / total_days
        avg_apnea = sum(d['apnea_index'] for d in daily_metrics) / total_days
        avg_hypopnea = sum(d['hypopnea_index'] for d in daily_metrics) / total_days
        avg_leak = sum(d['leak'] for d in daily_metrics) / total_days
        avg_central = sum(d['central_index'] for d in daily_metrics) / total_days
        avg_obstructive = sum(d['obstructive_index'] for d in daily_metrics) / total_days
        
        # BiPAP metrics averages
        avg_tidal = total_tidal / total_days if total_days > 0 else 0
        avg_rr = total_rr / total_days if total_days > 0 else 0
        avg_mv = total_mv / total_days if total_days > 0 else 0
        avg_tidal_95 = total_tidal_95 / total_days if total_days > 0 else 0
        avg_rr_95 = total_rr_95 / total_days if total_days > 0 else 0
        avg_mv_95 = total_mv_95 / total_days if total_days > 0 else 0
        avg_ipap = total_ipap / total_days if total_days > 0 else 0
        avg_epap = total_epap / total_days if total_days > 0 else 0
        
        return {
            'avg_max': round(avg_max, 1),
            'avg_median': round(avg_median, 1),
            'avg_percentile_95': round(avg_percentile_95, 1),
            'avg_set_pressure': round(avg_set_pressure, 1),
            'avg_ahi': round(avg_ahi, 2),
            'avg_apnea': round(avg_apnea, 2),
            'avg_hypopnea': round(avg_hypopnea, 2),
            'avg_leak': round(avg_leak, 2),
            'avg_central': round(avg_central, 2),
            'avg_obstructive': round(avg_obstructive, 2),
            'total_days': total_days,
            'total_minutes': round(total_minutes, 1),
            'total_hours': round(total_hours, 2),
            'total_central': total_central,
            'total_obstructive': total_obstructive,
            'total_hypopnea': total_hypopnea,
            
            # BiPAP metrics
            'avg_tidal_volume': round(avg_tidal, 1),
            'avg_respiratory_rate': round(avg_rr, 1),
            'avg_minute_ventilation': round(avg_mv, 1),
            'avg_tidal_volume_95': round(avg_tidal_95, 1),
            'avg_respiratory_rate_95': round(avg_rr_95, 1),
            'avg_minute_ventilation_95': round(avg_mv_95, 1),
            'avg_ipap': round(avg_ipap, 1),
            'avg_epap': round(avg_epap, 1)
        }


class DeviceModeProcessor:
    """Process device mode and settings information"""
    
    @staticmethod
    def get_device_info(mode, serial_number=""):
        """Get device information based on mode"""
        mode_str = str(mode).strip()
        
        mode_info = {
            'mode_name': 'Unknown',
            'device': 'Unknown',
            'is_cpap': False,
            'is_bipap': False,
            'is_auto': False,
            'is_manual': False
        }
        
        has_serial = serial_number and serial_number != '' and serial_number.lower() != 'unknown'
        
        if mode_str in ['1', '01']:
            mode_info['mode_name'] = 'MANUAL CPAP'
            mode_info['device'] = 'VT 30D' if has_serial else 'VT 40D / VT 50D'
            mode_info['is_cpap'] = True
            mode_info['is_manual'] = True
            
        elif mode_str in ['2', '02']:
            mode_info['mode_name'] = 'AUTO CPAP'
            mode_info['device'] = 'VT 30D' if has_serial else 'VT 40D / VT 50D'
            mode_info['is_cpap'] = True
            mode_info['is_auto'] = True
            
        elif mode_str in ['3', '03']:
            mode_info['mode_name'] = 'MANUAL CPAP'
            mode_info['device'] = 'VT 30D' if has_serial else 'VT 40D / VT 50D'
            mode_info['is_cpap'] = True
            mode_info['is_manual'] = True
            
        elif mode_str in ['4', '04']:
            mode_info['mode_name'] = 'AUTO CPAP'
            mode_info['device'] = 'VT 30D' if has_serial else 'VT 40D / VT 50D'
            mode_info['is_cpap'] = True
            mode_info['is_auto'] = True
            
        elif mode_str in ['5', '05']:
            mode_info['mode_name'] = 'BiPAP (CPAP MODE)'
            mode_info['device'] = 'VT 60 ST' if has_serial else 'VT 100 / VT 200'
            mode_info['is_bipap'] = True
            
        elif mode_str in ['7', '07']:
            mode_info['mode_name'] = 'BiPAP (S MODE)'
            mode_info['device'] = 'VT 60 ST' if has_serial else 'VT 100 / VT 200'
            mode_info['is_bipap'] = True
            
        elif mode_str in ['8', '08']:
            mode_info['mode_name'] = 'BiPAP (T MODE)'
            mode_info['device'] = 'VT 60 ST' if has_serial else 'VT 100 / VT 200'
            mode_info['is_bipap'] = True
            
        elif mode_str in ['9', '09']:
            mode_info['mode_name'] = 'BiPAP (ST MODE)'
            mode_info['device'] = 'VT 60 ST' if has_serial else 'VT 100 / VT 200'
            mode_info['is_bipap'] = True
            
        elif mode_str == '11':
            mode_info['mode_name'] = 'BiPAP (VAPS MODE)'
            mode_info['device'] = 'VT 60 ST' if has_serial else 'VT 200'
            mode_info['is_bipap'] = True
            
        elif mode_str in ['13', '14', '16']:
            mode_info['mode_name'] = 'BiPAP'
            mode_info['device'] = 'BiPAP Device'
            mode_info['is_bipap'] = True
        
        return mode_info
    
    @staticmethod
    def get_mask_type(mask_value):
        """Get mask type from value"""
        mask_str = str(mask_value).strip()
        
        if mask_str in ['1', '01']:
            return 'Nasal Mask'
        elif mask_str in ['2', '02']:
            return 'Full face Mask'
        elif mask_str in ['3', '03']:
            return 'Pillow Mask'
        elif mask_str.isdigit() and int(mask_str) > 5:
            return 'NULL'
        else:
            return 'Unknown'
    
    @staticmethod
    def get_flex_info(flex_value, flex_level):
        """Get A-Flex information"""
        flex_str = str(flex_value).strip()
        level_str = str(flex_level).strip()
        
        if flex_str.isdigit() and int(flex_str) > 2:
            return {'flex_value': 'N/A', 'flex_level': 'N/A'}
        
        if flex_str in ['1', '01']:
            flex_display = 'ON'
            if level_str in ['1', '01']:
                level = '1'
            elif level_str in ['2', '02']:
                level = '2'
            elif level_str in ['3', '03']:
                level = '3'
            else:
                level = 'Unknown'
        elif flex_str in ['2', '02']:
            flex_display = 'OFF'
            level = '0'
        else:
            flex_display = 'N/A'
            level = 'N/A'
        
        return {'flex_value': flex_display, 'flex_level': level}
    
    @staticmethod
    def get_primary_mode(sessions):
        """Get the most frequent mode from sessions"""
        if not sessions:
            return '0'
        modes = [s['mode'] for s in sessions if s.get('mode')]
        if not modes:
            return '0'
        # Count frequencies
        mode_counts = Counter(modes)
        # Return most common mode
        return mode_counts.most_common(1)[0][0]


class CPAPCalculations:
    """Main calculations class for CPAP/BiPAP data processing"""
    
    CUTOFF_HOUR = 12  # Therapy day cutoff (12:00 PM = Noon cutoff)
    
    @staticmethod
    def is_valid_data_row(row_data):
        """Check if row has valid data"""
        if len(row_data) < 25:
            return False
        
        try:
            year1 = row_data[3] if len(row_data) > 3 else '0'
            year2 = row_data[6] if len(row_data) > 6 else '0'
            month = row_data[2] if len(row_data) > 2 else '0'
            day = row_data[1] if len(row_data) > 1 else '0'
            end_hour = row_data[21] if len(row_data) > 21 else '0'
            end_min = row_data[22] if len(row_data) > 22 else '0'
            
            if any(val == '255' for val in [day, month, year1, year2, end_hour, end_min]):
                return False
            
            return (int(year1) > 22 and int(year2) > 22 and 
                    month not in ['0', '00'] and
                    day not in ['0', '00'] and
                    (end_hour != '0' or end_min != '0'))
            
        except (ValueError, IndexError):
            return False

    @staticmethod
    def get_therapy_date(start_datetime):
        """Determine therapy date based on noon cutoff"""
        try:
            if isinstance(start_datetime, str):
                dt = datetime.strptime(start_datetime, '%Y-%m-%d %H:%M')
            else:
                dt = start_datetime
            
            if dt.hour < CPAPCalculations.CUTOFF_HOUR:
                therapy_date = dt - timedelta(days=1)
            else:
                therapy_date = dt
            
            return therapy_date.date()
            
        except Exception:
            return start_datetime.date() if hasattr(start_datetime, 'date') else datetime.now().date()

    @staticmethod
    def calculate_session_duration(start_time, end_time):
        """Calculate session duration in minutes"""
        try:
            total_minutes = abs((end_time - start_time).total_seconds()) / 60
            
            if total_minutes < 0:
                total_minutes += 1440
            
            return round(total_minutes, 1)
            
        except Exception:
            return 0.0

    @staticmethod
    def calculate_pressure(max_pressure, min_pressure, pressure_change_count, mode):
        """Calculate pressure metrics"""
        return PressureCalculator.calculate_pressure(
            max_pressure, min_pressure, pressure_change_count, mode
        )

    @staticmethod
    def calculate_event_indices(central_count, obstructive_count, hypopnea_count, usage_minutes, mode):
        """Calculate event indices"""
        return PressureCalculator.calculate_event_indices(
            central_count, obstructive_count, hypopnea_count, usage_minutes, mode
        )

    @staticmethod
    def adjust_leak_value(raw_leak):
        """Adjust leak value"""
        return PressureCalculator.adjust_leak_value(raw_leak)

    @staticmethod
    def calculate_daily_totals(sessions):
        """Calculate daily totals"""
        if not sessions:
            return []
        
        daily_groups = defaultdict(list)
        for session in sessions:
            daily_groups[session['therapy_date_str']].append(session)
        
        daily_totals = []
        
        for therapy_date_str, date_sessions in daily_groups.items():
            valid_sessions = [s for s in date_sessions if s['duration_minutes'] >= 30]
            
            if not valid_sessions:
                continue
            
            valid_sessions.sort(key=lambda x: x['device_start_dt'])
            
            aggregator = DailyPressureAggregator()
            aggregator.same_day_counter = len(valid_sessions)
            
            daily_data = None
            
            for i, session in enumerate(valid_sessions):
                is_last = (i == len(valid_sessions) - 1)
                
                aggregator_session = {
                    'mode': session['mode'],
                    'calculated_max': session['calculated_max'],
                    'median': session['median_pressure'],
                    'percentile_95': session['percentile_95_pressure'],
                    'min_pressure': session['min_pressure_setting'],
                    'max_pressure_setting': session['max_pressure_setting'],
                    'pressure_change_count': session['pressure_change_count'],
                    'central_count': session['central_count'],
                    'obstructive_count': session['obstructive_count'],
                    'hypopnea_count': session['hypopnea_count'],
                    'leak': session['leak'],
                    'duration_minutes': session['duration_minutes'],
                    
                    # BiPAP metrics
                    'tidal_volume': session.get('tidal_volume', 0.0),
                    'respiratory_rate': session.get('respiratory_rate', 0.0),
                    'minute_ventilation': session.get('minute_ventilation', 0.0),
                    'tidal_volume_95': session.get('tidal_volume_95', 0.0),
                    'respiratory_rate_95': session.get('respiratory_rate_95', 0.0),
                    'minute_ventilation_95': session.get('minute_ventilation_95', 0.0)
                }
                
                daily_data = aggregator.process_daily_pressure(
                    aggregator_session, 
                    is_last_session=is_last
                )
                
                if daily_data and is_last:
                    daily_data['date'] = session['therapy_date']
                    daily_data['date_str'] = therapy_date_str
                    daily_data['display_date'] = session['therapy_date'].strftime('%d %b')
                    daily_data['sessions_count'] = len(valid_sessions)
                    
                    daily_data['device_info'] = valid_sessions[0]['device_info']
                    daily_data['mode_name'] = valid_sessions[0]['mode_name']
                    daily_data['flex_value'] = valid_sessions[0]['flex_info']
                    daily_data['flex_level'] = valid_sessions[0]['flex_level']
                    daily_data['mask_type'] = valid_sessions[0]['mask_type']
                    
                    daily_data['category'] = '≥4 hours' if daily_data['total_minutes'] >= 240 else '<4 hours'
                    
                    daily_totals.append(daily_data)
        
        daily_totals.sort(key=lambda x: x['date'])
        return daily_totals

    @staticmethod
    def calculate_overall_metrics(daily_metrics):
        """Calculate overall metrics"""
        if not daily_metrics:
            return CPAPCalculations._empty_overall_metrics()
        
        overall_metrics = OverallPressureMetrics.calculate_overall_averages(daily_metrics)
        
        if daily_metrics:
            overall_metrics['device_info'] = Counter([d['device_info'] for d in daily_metrics]).most_common(1)[0][0]
            overall_metrics['mode_name'] = Counter([d['mode_name'] for d in daily_metrics]).most_common(1)[0][0]
            overall_metrics['flex_info'] = Counter([d['flex_value'] for d in daily_metrics]).most_common(1)[0][0]
            overall_metrics['flex_level'] = Counter([d['flex_level'] for d in daily_metrics]).most_common(1)[0][0]
            overall_metrics['mask_type'] = Counter([d['mask_type'] for d in daily_metrics]).most_common(1)[0][0]
        else:
            overall_metrics['device_info'] = 'Unknown'
            overall_metrics['mode_name'] = 'Unknown'
            overall_metrics['flex_info'] = 'N/A'
            overall_metrics['flex_level'] = '0'
            overall_metrics['mask_type'] = 'Unknown'
        
        overall_metrics['usage_hours_formatted'] = CPAPCalculations.format_minutes_to_hours_minutes(
            overall_metrics['total_minutes']
        )
        
        return overall_metrics

    @staticmethod
    def _empty_overall_metrics():
        """Return empty overall metrics"""
        return {
            'avg_max': 0.0,
            'avg_median': 0.0,
            'avg_percentile_95': 0.0,
            'avg_set_pressure': 0.0,
            'avg_ahi': 0.0,
            'avg_apnea': 0.0,
            'avg_hypopnea': 0.0,
            'avg_leak': 0.0,
            'avg_central': 0.0,
            'avg_obstructive': 0.0,
            'total_days': 0,
            'total_minutes': 0,
            'total_hours': 0.0,
            'total_central': 0,
            'total_obstructive': 0,
            'total_hypopnea': 0,
            'usage_hours_formatted': "00 Hours, 00 Minutes",
            'device_info': 'Unknown',
            'mode_name': 'Unknown',
            'flex_info': 'N/A',
            'flex_level': '0',
            'mask_type': 'Unknown',
            
            # BiPAP metrics
            'avg_tidal_volume': 0.0,
            'avg_respiratory_rate': 0.0,
            'avg_minute_ventilation': 0.0,
            'avg_tidal_volume_95': 0.0,
            'avg_respiratory_rate_95': 0.0,
            'avg_minute_ventilation_95': 0.0,
            'avg_ipap': 0.0,
            'avg_epap': 0.0
        }

    @staticmethod
    def format_minutes_to_hours_minutes(minutes):
        """Convert minutes to HH Hours, MM Minutes format"""
        try:
            total_minutes = round(minutes)
            hours = math.floor(total_minutes / 60)
            minutes_remainder = total_minutes % 60
            return f"{hours:02d} Hours, {minutes_remainder:02d} Minutes"
        except:
            return "00 Hours, 00 Minutes"

    @staticmethod
    def parse_session_from_csv(line):
        """Parse a single CSV line - exact indices from PHP code"""
        try:
            line = line.strip()
            if not line or line.startswith('#'):
                return None
            
            parts = line.split(',')
            
            if not CPAPCalculations.is_valid_data_row(parts):
                return None
            
            # Extract data with exact PHP indices
            serial_number = parts[-1].strip() if parts else "Unknown"
            mode = parts[7].strip() if len(parts) > 7 else '0'
            
            try:
                device_day = int(parts[1]) if len(parts) > 1 and parts[1].strip() and parts[1] not in ['0', '00', '255'] else 1
                device_month = int(parts[2]) if len(parts) > 2 and parts[2].strip() and parts[2] not in ['0', '00', '255'] else 1
                device_year = int(parts[3]) if len(parts) > 3 and parts[3].strip() and parts[3] not in ['0', '00', '255'] else 2025
                
                start_hour = int(parts[19]) if len(parts) > 19 and parts[19].strip() and parts[19] not in ['0', '00', '255'] else 0
                start_min = int(parts[20]) if len(parts) > 20 and parts[20].strip() and parts[20] not in ['0', '00', '255'] else 0
                
                end_day = int(parts[4]) if len(parts) > 4 and parts[4].strip() and parts[4] not in ['0', '00', '255'] else device_day
                end_month = int(parts[5]) if len(parts) > 5 and parts[5].strip() and parts[5] not in ['0', '00', '255'] else device_month
                end_year = int(parts[6]) if len(parts) > 6 and parts[6].strip() and parts[6] not in ['0', '00', '255'] else device_year
                end_hour = int(parts[21]) if len(parts) > 21 and parts[21].strip() and parts[21] not in ['0', '00', '255'] else 0
                end_min = int(parts[22]) if len(parts) > 22 and parts[22].strip() and parts[22] not in ['0', '00', '255'] else 0
                
            except (ValueError, IndexError):
                return None
            
            if 0 < device_year < 100:
                device_year += 2000
            if 0 < end_year < 100:
                end_year += 2000
            
            device_start_time = datetime(device_year, device_month, device_day, start_hour, start_min)
            device_end_time = datetime(end_year, end_month, end_day, end_hour, end_min)
            
            session_minutes = CPAPCalculations.calculate_session_duration(device_start_time, device_end_time)
            
            if session_minutes < 30:
                return None
            
            therapy_date = CPAPCalculations.get_therapy_date(device_start_time)
            
            # Extract pressure settings - indices 9 and 10
            try:
                max_pressure = float(parts[9]) if len(parts) > 9 and parts[9].strip() and parts[9] not in ['0', '00', '255'] else 8.0
                min_pressure = float(parts[10]) if len(parts) > 10 and parts[10].strip() and parts[10] not in ['0', '00', '255'] else 4.0
                pressure_change_count = int(parts[13]) if len(parts) > 13 and parts[13].strip() and parts[13] not in ['0', '00', '255'] else 0
            except (ValueError, IndexError):
                max_pressure, min_pressure, pressure_change_count = 8.0, 4.0, 0
            
            pressure_data = CPAPCalculations.calculate_pressure(
                max_pressure, min_pressure, pressure_change_count, mode
            )
            
            # Extract event counts - indices 28, 29, 30
            try:
                central_count = int(parts[28]) if len(parts) > 28 and parts[28].strip() and parts[28] not in ['0', '00', '255'] else 0
                obstructive_count = int(parts[29]) if len(parts) > 29 and parts[29].strip() and parts[29] not in ['0', '00', '255'] else 0
                hypopnea_count = int(parts[30]) if len(parts) > 30 and parts[30].strip() and parts[30] not in ['0', '00', '255'] else 0
            except (ValueError, IndexError):
                central_count = obstructive_count = hypopnea_count = 0
            
            event_data = CPAPCalculations.calculate_event_indices(
                central_count, obstructive_count, hypopnea_count, session_minutes, mode
            )
            
            # Extract leak - index 38
            try:
                leak_raw = float(parts[38]) if len(parts) > 38 and parts[38].strip() and parts[38] not in ['0', '00', '255'] else 0.0
                leak = CPAPCalculations.adjust_leak_value(leak_raw)
            except (ValueError, IndexError):
                leak = 0.0
            
            device_info = DeviceModeProcessor.get_device_info(mode, serial_number)
            
            # Extract flex settings - indices 33 and 34
            try:
                flex_setting = parts[33] if len(parts) > 33 and parts[33].strip() and parts[33] not in ['0', '00', '255'] else '0'
                flex_level_raw = parts[34] if len(parts) > 34 and parts[34].strip() and parts[34] not in ['0', '00', '255'] else '0'
                flex_info = DeviceModeProcessor.get_flex_info(flex_setting, flex_level_raw)
            except (ValueError, IndexError):
                flex_setting, flex_level_raw, flex_info = '0', '0', {'flex_value': 'N/A', 'flex_level': 'N/A'}
            
            # Extract mask type - index 36
            try:
                mask_type_raw = parts[36] if len(parts) > 36 and parts[36].strip() and parts[36] not in ['0', '00', '255'] else '0'
                mask_type = DeviceModeProcessor.get_mask_type(mask_type_raw)
            except (ValueError, IndexError):
                mask_type_raw, mask_type = '0', 'Unknown'
            
            if mode in ['1', '01', '3', '03', '5', '05']:
                set_pressure = min_pressure if min_pressure > 0 else max_pressure
            else:
                set_pressure = min_pressure
            
            # Extract BiPAP metrics:
            # Tidal Volume - index 16
            try:
                tidal_volume_raw = parts[16] if len(parts) > 16 and parts[16].strip() and parts[16] not in ['0', '00', '255'] else '0'
                tidal_volume = float(tidal_volume_raw)
            except (ValueError, IndexError):
                tidal_volume = 0.0
            
            # Respiratory Rate - index 17
            try:
                respiratory_rate_raw = parts[17] if len(parts) > 17 and parts[17].strip() and parts[17] not in ['0', '00', '255'] else '0'
                respiratory_rate = float(respiratory_rate_raw)
            except (ValueError, IndexError):
                respiratory_rate = 0.0
            
            # Minute Ventilation - index 27 - convert as per PHP: ($value*10)/100 = $value*0.1
            try:
                minute_ventilation_raw = parts[27] if len(parts) > 27 and parts[27].strip() and parts[27] not in ['0', '00', '255'] else '0'
                minute_ventilation = float(minute_ventilation_raw) * 0.1
            except (ValueError, IndexError):
                minute_ventilation = 0.0
            
            # Calculate 95th percentiles using factor 0.83 (as in PHP)
            tidal_volume_95 = tidal_volume * 0.83
            respiratory_rate_95 = respiratory_rate * 0.83
            minute_ventilation_95 = minute_ventilation * 0.83
            
            return {
                'serial_number': serial_number,
                'mode': mode,
                'mode_name': device_info['mode_name'],
                'device_info': device_info['device'],
                
                'therapy_date': therapy_date,
                'therapy_date_str': therapy_date.strftime('%Y-%m-%d'),
                'device_start_dt': device_start_time,
                'device_end_dt': device_end_time,
                
                'duration_minutes': session_minutes,
                'usage_hours': session_minutes / 60.0,
                
                'max_pressure_setting': max_pressure,
                'min_pressure_setting': min_pressure,
                'calculated_max': pressure_data['calculated_max'],
                'rounded_max': pressure_data['rounded_max'],
                'median_pressure': pressure_data['median'],
                'percentile_95_pressure': pressure_data['percentile_95'],
                'pressure_change_count': pressure_data['pressure_change_count'],
                'graph_pressure': round(pressure_data['percentile_95'], 1),
                'set_pressure': round(set_pressure, 1),
                'is_fixed_pressure': pressure_data['is_manual_mode'],
                
                'central_count': central_count,
                'obstructive_count': obstructive_count,
                'hypopnea_count': hypopnea_count,
                
                'ahi_index': event_data['ahi'],
                'apnea_index': event_data['apnea'],
                'hypopnea_index': event_data['hypopnea'],
                'central_index': event_data['central'],
                'obstructive_index': event_data['obstructive'],
                
                'leak': leak,
                'leak_raw': leak_raw,
                
                'flex_info': flex_info['flex_value'],
                'flex_level': flex_info['flex_level'],
                'mask_type_raw': mask_type_raw,
                'mask_type': mask_type,
                
                # BiPAP metrics
                'tidal_volume': tidal_volume,
                'respiratory_rate': respiratory_rate,
                'minute_ventilation': minute_ventilation,
                'tidal_volume_95': tidal_volume_95,
                'respiratory_rate_95': respiratory_rate_95,
                'minute_ventilation_95': minute_ventilation_95,
                
                'raw_line': line,
                'therapy_hours': event_data['usage_hours']
            }
            
        except Exception as e:
            print(f"Error parsing session: {e}")
            return None

    @staticmethod
    def calculate_usage_statistics(sessions, from_date, to_date):
        """Calculate usage statistics"""
        if not sessions:
            return CPAPCalculations._empty_usage_stats()
        
        report_duration = (to_date - from_date).days + 1
        
        daily_totals = CPAPCalculations.calculate_daily_totals(sessions)
        
        daily_totals_in_range = [
            d for d in daily_totals 
            if from_date <= d['date'] <= to_date
        ]
        
        days_with_usage = len(daily_totals_in_range)
        total_minutes = sum(d['total_minutes'] for d in daily_totals_in_range)
        
        greater_than_4_hours = sum(1 for d in daily_totals_in_range if d['total_minutes'] >= 240)
        less_than_4_hours = days_with_usage - greater_than_4_hours
        
        if report_duration > 0:
            usage_percentage = (days_with_usage / report_duration) * 100
            greater_than_4_percentage = (greater_than_4_hours / report_duration) * 100
            less_than_4_percentage = (less_than_4_hours / report_duration) * 100
        else:
            usage_percentage = greater_than_4_percentage = less_than_4_percentage = 0.0
        
        return CPAPCalculations._format_usage_stats(
            total_minutes, report_duration, days_with_usage,
            greater_than_4_hours, less_than_4_hours,
            usage_percentage, greater_than_4_percentage, less_than_4_percentage,
            daily_totals_in_range
        )

    @staticmethod
    def _empty_usage_stats():
        """Return empty usage statistics"""
        return {
            'usage_days': "0/0 Days (0.00%)",
            'greater_than_4': "0 (0.00%)",
            'less_than_4': "0 (0.00%)",
            'usage_hours': "00 Hours, 00 Minutes",
            'usage_hours_decimal': "0.00 hours",
            'avg_total_days': "00 Hours, 00 Minutes",
            'avg_total_days_decimal': "0.00 hours",
            'avg_days_used': "00 Hours, 00 Minutes",
            'avg_days_used_decimal': "0.00 hours",
            'median_days_used': "00 Hours, 00 Minutes",
            'median_days_used_decimal': "0.00 hours",
            'total_minutes': 0,
            'total_hours': 0,
            'days_with_usage': 0,
            'greater_than_4_count': 0,
            'less_than_4_count': 0,
            'report_duration': 0,
            'daily_totals': [],
            'avg_total_minutes': 0,
            'avg_used_minutes': 0,
            'median_minutes': 0
        }

    @staticmethod
    def _format_usage_stats(total_minutes, report_duration, days_with_usage,
                           greater_than_4_hours, less_than_4_hours,
                           usage_percentage, greater_than_4_percentage, less_than_4_percentage,
                           daily_totals_in_range):
        """Format usage statistics"""
        total_minutes_rounded = round(total_minutes)
        
        usage_hours_formatted = CPAPCalculations.format_minutes_to_hours_minutes(total_minutes_rounded)
        usage_hours_decimal = total_minutes / 60.0
        
        avg_total_formatted, avg_total_decimal, avg_total_minutes_rounded = \
            CPAPCalculations._calculate_avg_total(total_minutes, report_duration)
        
        avg_used_formatted, avg_used_decimal, avg_used_minutes_rounded = \
            CPAPCalculations._calculate_avg_used(total_minutes, days_with_usage)
        
        median_formatted, median_decimal, median_minutes_rounded = \
            CPAPCalculations._calculate_median(total_minutes, greater_than_4_hours)
        
        return {
            'usage_days': f"{days_with_usage}/{report_duration} Days ({usage_percentage:.2f}%)",
            'greater_than_4': f"{greater_than_4_hours} ({greater_than_4_percentage:.2f}%)",
            'less_than_4': f"{less_than_4_hours} ({less_than_4_percentage:.2f}%)",
            'usage_hours': usage_hours_formatted,
            'usage_hours_decimal': f"{usage_hours_decimal:.2f} hours",
            'avg_total_days': avg_total_formatted,
            'avg_total_days_decimal': f"{avg_total_decimal:.2f} hours",
            'avg_days_used': avg_used_formatted,
            'avg_days_used_decimal': f"{avg_used_decimal:.2f} hours",
            'median_days_used': median_formatted,
            'median_days_used_decimal': f"{median_decimal:.2f} hours",
            'total_minutes': total_minutes,
            'total_hours': usage_hours_decimal,
            'days_with_usage': days_with_usage,
            'greater_than_4_count': greater_than_4_hours,
            'less_than_4_count': less_than_4_hours,
            'report_duration': report_duration,
            'avg_total_minutes': avg_total_minutes_rounded,
            'avg_used_minutes': avg_used_minutes_rounded,
            'median_minutes': median_minutes_rounded,
            'daily_totals': daily_totals_in_range
        }

    @staticmethod
    def _calculate_avg_total(total_minutes, report_duration):
        """Calculate average for total days"""
        if report_duration > 0:
            avg_total_minutes_rounded = round(total_minutes / report_duration)
            avg_total_hours = math.floor(avg_total_minutes_rounded / 60)
            avg_total_mins = avg_total_minutes_rounded % 60
            avg_total_formatted = f"{avg_total_hours:02d} Hours, {avg_total_mins:02d} Minutes"
            avg_total_decimal = total_minutes / report_duration / 60.0
            return avg_total_formatted, avg_total_decimal, avg_total_minutes_rounded
        return "00 Hours, 00 Minutes", 0.0, 0

    @staticmethod
    def _calculate_avg_used(total_minutes, days_with_usage):
        """Calculate average for days used"""
        if days_with_usage > 0:
            avg_used_minutes_rounded = round(total_minutes / days_with_usage)
            avg_used_hours = math.floor(avg_used_minutes_rounded / 60)
            avg_used_mins = avg_used_minutes_rounded % 60
            avg_used_formatted = f"{avg_used_hours:02d} Hours, {avg_used_mins:02d} Minutes"
            avg_used_decimal = total_minutes / days_with_usage / 60.0
            return avg_used_formatted, avg_used_decimal, avg_used_minutes_rounded
        return "00 Hours, 00 Minutes", 0.0, 0

    @staticmethod
    def _calculate_median(total_minutes, greater_than_4_hours):
        """Calculate median for days used"""
        divisor = greater_than_4_hours if greater_than_4_hours > 0 else 1
        median_minutes_rounded = round(total_minutes / divisor)
        median_hours = math.floor(median_minutes_rounded / 60)
        median_mins = median_minutes_rounded % 60
        median_formatted = f"{median_hours:02d} Hours, {median_mins:02d} Minutes"
        median_decimal = total_minutes / divisor / 60.0
        return median_formatted, median_decimal, median_minutes_rounded

    @staticmethod
    def classify_ahi_severity(ahi):
        """Classify AHI severity"""
        if ahi < 5:
            return 'Normal'
        elif ahi < 15:
            return 'Mild'
        elif ahi < 30:
            return 'Moderate'
        else:
            return 'Severe'

    @staticmethod
    def calculate_leak_percentage_above_threshold(leak_values, threshold=24):
        """Calculate leak percentage above threshold"""
        if not leak_values:
            return 0
        
        above_threshold = sum(1 for value in leak_values if value > threshold)
        return (above_threshold / len(leak_values)) * 100


# ==================== Report Generator Class ====================

class ReportGenerator:
    """Generate comprehensive PDF reports with mode-specific content"""
    
    # Mode definitions based on the requirement table
    MODE_MANUAL_CPAP = ['1', '01', '3', '03']
    MODE_AUTO_CPAP = ['2', '02', '4', '04']
    MODE_BIPAP_CPAP = ['5', '05']  # BiPAP in CPAP mode - shows Apnea Index
    MODE_BIPAP_S = ['7', '07']      # BiPAP S mode - shows full metrics
    MODE_BIPAP_T = ['8', '08']      # BiPAP T mode - shows full metrics
    MODE_BIPAP_ST = ['9', '09']     # BiPAP ST mode - shows full metrics
    MODE_BIPAP_VAPS = ['11']        # BiPAP VAPS mode - shows full metrics
    
    @staticmethod
    def is_cpap_mode(mode):
        """Check if mode is CPAP (Manual or Auto)"""
        mode_str = str(mode)
        return (mode_str in ReportGenerator.MODE_MANUAL_CPAP or 
                mode_str in ReportGenerator.MODE_AUTO_CPAP)
    
    @staticmethod
    def is_bipap_cpap_mode(mode):
        """Check if mode is BiPAP in CPAP mode (mode 5/05)"""
        mode_str = str(mode)
        return mode_str in ReportGenerator.MODE_BIPAP_CPAP
    
    @staticmethod
    def is_full_bipap_mode(mode):
        """Check if mode is full BiPAP with all metrics (S/T/ST/VAPS)"""
        mode_str = str(mode)
        return (mode_str in ReportGenerator.MODE_BIPAP_S or
                mode_str in ReportGenerator.MODE_BIPAP_T or
                mode_str in ReportGenerator.MODE_BIPAP_ST or
                mode_str in ReportGenerator.MODE_BIPAP_VAPS)
    
    @staticmethod
    def get_mode_display_name(mode):
        """Get display name for mode"""
        mode_str = str(mode)
        if mode_str in ReportGenerator.MODE_MANUAL_CPAP:
            return "MANUAL CPAP"
        elif mode_str in ReportGenerator.MODE_AUTO_CPAP:
            return "AUTO CPAP"
        elif mode_str in ReportGenerator.MODE_BIPAP_CPAP:
            return "BiPAP (CPAP MODE)"
        elif mode_str in ReportGenerator.MODE_BIPAP_S:
            return "BiPAP (S MODE)"
        elif mode_str in ReportGenerator.MODE_BIPAP_T:
            return "BiPAP (T MODE)"
        elif mode_str in ReportGenerator.MODE_BIPAP_ST:
            return "BiPAP (ST MODE)"
        elif mode_str in ReportGenerator.MODE_BIPAP_VAPS:
            return "BiPAP (VAPS MODE)"
        else:
            return "CPAP (fallback)"
    
    @staticmethod
    def calculate_median_from_array(values):
        """Calculate median from array of values"""
        if not values:
            return 0.0
        sorted_values = sorted(values)
        n = len(sorted_values)
        if n % 2 == 0:
            return (sorted_values[n//2 - 1] + sorted_values[n//2]) / 2
        else:
            return sorted_values[n//2]
    
    def generate_pdf_report(self, sessions, daily_metrics, overall_metrics, usage_stats, 
                           serial, from_date, to_date, primary_mode='0'):
        """Generate PDF report with mode-specific content"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"Therapy_Report_{serial}_{timestamp}.pdf"
            
            doc = SimpleDocTemplate(filename, pagesize=A4, 
                                   rightMargin=72, leftMargin=72,
                                   topMargin=72, bottomMargin=18)
            
            styles = getSampleStyleSheet()
            story = []
            
            # Create custom styles
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontSize=16,
                textColor=colors.HexColor('#1e3a8a'),
                alignment=1,  # Center alignment
                spaceAfter=30
            )
            
            heading_style = ParagraphStyle(
                'CustomHeading',
                parent=styles['Heading2'],
                fontSize=14,
                textColor=colors.HexColor('#3b82f6'),
                spaceAfter=12,
                spaceBefore=12
            )
            
            subheading_style = ParagraphStyle(
                'CustomSubHeading',
                parent=styles['Heading3'],
                fontSize=12,
                textColor=colors.HexColor('#475569'),
                spaceAfter=8,
                spaceBefore=8
            )
            
            normal_style = styles['Normal']
            
            # Get mode display name
            mode_display_name = self.get_mode_display_name(primary_mode)
            
            # Title
            story.append(Paragraph(f"Therapy Report", title_style))
            story.append(Paragraph(f"Serial Number: {serial}", normal_style))
            story.append(Paragraph(f"Period: {from_date.strftime('%d %b %Y')} to {to_date.strftime('%d %b %Y')}", normal_style))
            story.append(Paragraph(f"Mode: {mode_display_name} (Mode {primary_mode})", normal_style))
            story.append(Spacer(1, 0.2*inch))
            
            # Device Information Table
            story.append(Paragraph("Device Information", heading_style))
            
            device_data = [
                ["Device", overall_metrics.get('device_info', 'Unknown')],
                ["Mode", mode_display_name],
                ["A-Flex", overall_metrics.get('flex_info', 'N/A')],
                ["A-Flex Level", overall_metrics.get('flex_level', '0')],
                ["Mask Type", overall_metrics.get('mask_type', 'Unknown')],
                ["Set Pressure", f"{overall_metrics.get('avg_set_pressure', 0.0):.1f} cmH₂O"]
            ]
            
            device_table = Table(device_data, colWidths=[2*inch, 4*inch])
            device_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f1f5f9')),
                ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#1e3a8a')),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e2e8f0'))
            ]))
            story.append(device_table)
            story.append(Spacer(1, 0.2*inch))
            
            # Therapy Table - Mode specific content
            story.append(Paragraph("Therapy Metrics", heading_style))
            
            # Base metrics common to all modes
            therapy_data = [
                ["Metric", "Value"],
                ["Events per hour - AI", f"{overall_metrics.get('avg_apnea', 0.0):.2f}"],
                ["Events per hour - HI", f"{overall_metrics.get('avg_hypopnea', 0.0):.2f}"],
                ["Events per hour - AHI", f"{overall_metrics.get('avg_ahi', 0.0):.2f}"],
                ["Average Leak (L/min)", f"{overall_metrics.get('avg_leak', 0.0):.2f}"]
            ]
            
            # Add pressure metrics based on mode
            if self.is_cpap_mode(primary_mode):
                # CPAP modes show pressure metrics at top
                pressure_rows = [
                    ["Pressure - Set", f"{overall_metrics.get('avg_set_pressure', 0.0):.1f} cmH₂O"],
                    ["Pressure - 95th Percentile", f"{overall_metrics.get('avg_percentile_95', 0.0):.1f} cmH₂O"],
                    ["Pressure - Maximum", f"{overall_metrics.get('avg_max', 0.0):.1f} cmH₂O"]
                ]
                therapy_data[1:1] = pressure_rows
                
            elif self.is_bipap_cpap_mode(primary_mode):
                # BiPAP CPAP mode shows Apnea Index breakdown
                apnea_rows = [
                    ["Apnea Index - Central", f"{overall_metrics.get('avg_central', 0.0):.2f}"],
                    ["Apnea Index - Obstructive", f"{overall_metrics.get('avg_obstructive', 0.0):.2f}"],
                    ["Apnea Index - Unknown", "0.00"]
                ]
                therapy_data[4:4] = apnea_rows  # Insert after AHI
                
            elif self.is_full_bipap_mode(primary_mode):
                # Full BiPAP modes show additional respiratory metrics
                # Calculate medians properly from daily data
                tidal_values = [d.get('tidal_volume', 0) for d in daily_metrics if d.get('tidal_volume', 0) > 0]
                rr_values = [d.get('respiratory_rate', 0) for d in daily_metrics if d.get('respiratory_rate', 0) > 0]
                mv_values = [d.get('minute_ventilation', 0) for d in daily_metrics if d.get('minute_ventilation', 0) > 0]
                
                tidal_median = self.calculate_median_from_array(tidal_values) if tidal_values else 0
                rr_median = self.calculate_median_from_array(rr_values) if rr_values else 0
                mv_median = self.calculate_median_from_array(mv_values) if mv_values else 0
                
                respiratory_rows = [
                    ["Tidal Volume - Maximum", f"{overall_metrics.get('avg_tidal_volume', 0.0):.1f} mL"],
                    ["Tidal Volume - 95th Percentile", f"{overall_metrics.get('avg_tidal_volume_95', 0.0):.1f} mL"],
                    ["Tidal Volume - Median", f"{tidal_median:.1f} mL"],
                    ["Respiratory Rate - Maximum", f"{overall_metrics.get('avg_respiratory_rate', 0.0):.1f} bpm"],
                    ["Respiratory Rate - 95th Percentile", f"{overall_metrics.get('avg_respiratory_rate_95', 0.0):.1f} bpm"],
                    ["Respiratory Rate - Median", f"{rr_median:.1f} bpm"],
                    ["Minute Ventilation - Maximum", f"{overall_metrics.get('avg_minute_ventilation', 0.0):.1f} L/min"],
                    ["Minute Ventilation - 95th Percentile", f"{overall_metrics.get('avg_minute_ventilation_95', 0.0):.1f} L/min"],
                    ["Minute Ventilation - Median", f"{mv_median:.1f} L/min"]
                ]
                therapy_data.extend(respiratory_rows)
            
            # Create therapy table
            therapy_table = Table(therapy_data, colWidths=[3*inch, 3*inch])
            therapy_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3b82f6')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e2e8f0'))
            ]))
            story.append(therapy_table)
            story.append(Spacer(1, 0.2*inch))
            
            # Usage Statistics
            story.append(Paragraph("Usage Statistics", heading_style))
            
            usage_data = [
                ["Metric", "Value"],
                ["Usage Days", usage_stats.get('usage_days', '0/0 Days (0%)')],
                ["Days ≥ 4 hours", usage_stats.get('greater_than_4', '0 (0%)')],
                ["Days < 4 hours", usage_stats.get('less_than_4', '0 (0%)')],
                ["Total Usage Hours", usage_stats.get('usage_hours', '00 Hours, 00 Minutes')],
                ["Avg Usage (Total Days)", usage_stats.get('avg_total_days', '00 Hours, 00 Minutes')],
                ["Avg Usage (Days Used)", usage_stats.get('avg_days_used', '00 Hours, 00 Minutes')],
                ["Median Usage (Days Used)", usage_stats.get('median_days_used', '00 Hours, 00 Minutes')]
            ]
            
            usage_table = Table(usage_data, colWidths=[2.5*inch, 3.5*inch])
            usage_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3b82f6')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e2e8f0'))
            ]))
            story.append(usage_table)
            story.append(Spacer(1, 0.2*inch))
            
            # Generate and add graphs based on mode
            story.append(Paragraph("Therapy Graphs", heading_style))
            story.append(Spacer(1, 0.1*inch))
            
            # Usage Graph (common to all modes)
            usage_img = self.create_usage_graph(daily_metrics)
            if usage_img:
                story.append(Paragraph("Daily Usage Hours", subheading_style))
                story.append(usage_img)
                story.append(Spacer(1, 0.1*inch))
            
            # AHI Graph (common to all modes) - Modified to show stacked bars for BiPAP modes
            ahi_img = self.create_ahi_graph(daily_metrics, primary_mode)
            if ahi_img:
                story.append(Paragraph("Daily AHI (Events per Hour)", subheading_style))
                story.append(ahi_img)
                story.append(Spacer(1, 0.1*inch))
            
            # Pressure Graph (mode-specific)
            if self.is_cpap_mode(primary_mode):
                # CPAP modes show 95th percentile bar
                pressure_img = self.create_cpap_pressure_graph(daily_metrics)
                if pressure_img:
                    story.append(Paragraph("Daily 95th Percentile Pressure", subheading_style))
                    story.append(pressure_img)
                    story.append(Spacer(1, 0.1*inch))
            else:
                # BiPAP modes show stacked IPAP/EPAP
                pressure_img = self.create_bipap_pressure_graph(daily_metrics)
                if pressure_img:
                    story.append(Paragraph("Daily IPAP/EPAP Pressures", subheading_style))
                    story.append(pressure_img)
                    story.append(Spacer(1, 0.1*inch))
            
            # Leak Graph (common to all modes)
            leak_img = self.create_leak_graph(daily_metrics)
            if leak_img:
                story.append(Paragraph("Daily Leak Rate", subheading_style))
                story.append(leak_img)
                story.append(Spacer(1, 0.1*inch))
            
            # Additional graphs for full BiPAP modes
            if self.is_full_bipap_mode(primary_mode):
                story.append(PageBreak())
                story.append(Paragraph("Additional BiPAP Metrics", heading_style))
                
                # Tidal Volume Graph
                tidal_img = self.create_tidal_volume_graph(daily_metrics)
                if tidal_img:
                    story.append(Paragraph("Daily Tidal Volume", subheading_style))
                    story.append(tidal_img)
                    story.append(Spacer(1, 0.1*inch))
                
                # Respiratory Rate Graph
                rr_img = self.create_respiratory_rate_graph(daily_metrics)
                if rr_img:
                    story.append(Paragraph("Daily Respiratory Rate", subheading_style))
                    story.append(rr_img)
                    story.append(Spacer(1, 0.1*inch))
                
                # Minute Ventilation Graph
                mv_img = self.create_minute_ventilation_graph(daily_metrics)
                if mv_img:
                    story.append(Paragraph("Daily Minute Ventilation", subheading_style))
                    story.append(mv_img)
                    story.append(Spacer(1, 0.1*inch))
            
            # Build PDF
            doc.build(story)
            print(f"PDF report generated: {filename}")
            
            # Open PDF
            if os.name == 'nt':  # Windows
                os.startfile(filename)
            else:  # Linux/Mac
                os.system(f'xdg-open "{filename}"' if os.name == 'posix' else f'open "{filename}"')
            
            return True
            
        except Exception as e:
            print(f"Error generating PDF report: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def create_usage_graph(self, daily_metrics):
        """Create usage hours graph"""
        if not daily_metrics:
            return None
        
        try:
            fig, ax = plt.subplots(figsize=(8, 3))
            
            dates = [d['display_date'] for d in daily_metrics]
            usage_hours = [d['therapy_hours'] for d in daily_metrics]
            
            colors_list = ['#10b981' if h >= 4 else '#ef4444' for h in usage_hours]
            
            x_positions = range(len(dates))
            bars = ax.bar(x_positions, usage_hours, color=colors_list, alpha=0.8, width=0.7)
            
            ax.set_xticks(x_positions)
            ax.set_xticklabels(dates, rotation=45, ha='right', fontsize=8)
            
            ax.set_ylim(0, max(usage_hours) * 1.2 if usage_hours else 10)
            ax.set_ylabel('Hours')
            ax.grid(True, linestyle='--', alpha=0.3, axis='y')
            
            ax.axhline(y=4, color='red', linestyle='--', alpha=0.7, label='4 hour target')
            
            for bar, hours in zip(bars, usage_hours):
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                       f'{hours:.1f}', ha='center', va='bottom', fontsize=7)
            
            plt.tight_layout()
            
            img_buffer = BytesIO()
            plt.savefig(img_buffer, format='PNG', dpi=150, bbox_inches='tight')
            plt.close(fig)
            img_buffer.seek(0)
            
            return Image(img_buffer, width=6.5*inch, height=2.5*inch)
            
        except Exception as e:
            print(f"Error creating usage graph: {e}")
            return None
    
    def create_ahi_graph(self, daily_metrics, mode='0'):
        """Create AHI graph - stacked bars for BiPAP modes"""
        if not daily_metrics:
            return None
        
        try:
            fig, ax = plt.subplots(figsize=(8, 3))
            
            dates = [d['display_date'] for d in daily_metrics]
            
            if self.is_full_bipap_mode(mode) or self.is_bipap_cpap_mode(mode):
                # Stacked bar showing AI and HI components
                ai_values = [d['apnea_index'] for d in daily_metrics]
                hi_values = [d['hypopnea_index'] for d in daily_metrics]
                
                x_positions = range(len(dates))
                
                # Plot stacked bars
                ax.bar(x_positions, ai_values, label='AI', color='#f97316', alpha=0.8, width=0.7)
                ax.bar(x_positions, hi_values, bottom=ai_values, label='HI', color='#3b82f6', alpha=0.8, width=0.7)
                
                # Add total AHI labels
                for i, (ai, hi) in enumerate(zip(ai_values, hi_values)):
                    total = ai + hi
                    ax.text(i, total + 0.5, f'{total:.1f}', ha='center', va='bottom', fontsize=7)
                
                ax.legend(loc='upper right', fontsize=8)
                
            else:
                # Simple AHI bar for CPAP modes
                ahi_values = [d['ahi_index'] for d in daily_metrics]
                
                colors_list = []
                for value in ahi_values:
                    if value < 5:
                        colors_list.append('#27ae60')
                    elif value < 15:
                        colors_list.append('#f39c12')
                    elif value < 30:
                        colors_list.append('#e67e22')
                    else:
                        colors_list.append('#e74c3c')
                
                x_positions = range(len(dates))
                bars = ax.bar(x_positions, ahi_values, color=colors_list, alpha=0.8, width=0.7)
                
                # Add labels
                for bar, ahi in zip(bars, ahi_values):
                    height = bar.get_height()
                    ax.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                           f'{ahi:.1f}', ha='center', va='bottom', fontsize=7)
            
            ax.set_xticks(x_positions)
            ax.set_xticklabels(dates, rotation=45, ha='right', fontsize=8)
            
            max_ahi = max([d['ahi_index'] for d in daily_metrics]) if daily_metrics else 40
            ax.set_ylim(0, max_ahi + 5)
            ax.set_ylabel('Events per Hour')
            ax.grid(True, linestyle='--', alpha=0.3, axis='y')
            
            # Add severity threshold lines
            ax.axhline(y=5, color='green', linestyle='--', alpha=0.5, label='Normal (<5)')
            ax.axhline(y=15, color='orange', linestyle='--', alpha=0.5, label='Mild (<15)')
            
            plt.tight_layout()
            
            img_buffer = BytesIO()
            plt.savefig(img_buffer, format='PNG', dpi=150, bbox_inches='tight')
            plt.close(fig)
            img_buffer.seek(0)
            
            return Image(img_buffer, width=6.5*inch, height=2.5*inch)
            
        except Exception as e:
            print(f"Error creating AHI graph: {e}")
            return None
    
    def create_cpap_pressure_graph(self, daily_metrics):
        """Create pressure graph for CPAP modes (95th percentile bar)"""
        if not daily_metrics:
            return None
        
        try:
            fig, ax = plt.subplots(figsize=(8, 3))
            
            dates = [d['display_date'] for d in daily_metrics]
            pressure_values = [d['graph_pressure'] for d in daily_metrics]
            
            colors_list = ['#2f76cc' if p <= 15 else '#FF9800' if p <= 20 else '#F44336' 
                          for p in pressure_values]
            
            x_positions = range(len(dates))
            bars = ax.bar(x_positions, pressure_values, color=colors_list, alpha=0.8, width=0.7)
            
            ax.set_xticks(x_positions)
            ax.set_xticklabels(dates, rotation=45, ha='right', fontsize=8)
            
            ax.set_ylim(0, max(pressure_values) * 1.2 if pressure_values else 20)
            ax.set_ylabel('Pressure (cmH₂O)')
            ax.grid(True, linestyle='--', alpha=0.3, axis='y')
            
            for bar, pressure in zip(bars, pressure_values):
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height + 0.2,
                       f'{pressure:.1f}', ha='center', va='bottom', fontsize=7)
            
            plt.tight_layout()
            
            img_buffer = BytesIO()
            plt.savefig(img_buffer, format='PNG', dpi=150, bbox_inches='tight')
            plt.close(fig)
            img_buffer.seek(0)
            
            return Image(img_buffer, width=6.5*inch, height=2.5*inch)
            
        except Exception as e:
            print(f"Error creating CPAP pressure graph: {e}")
            return None
    
    def create_bipap_pressure_graph(self, daily_metrics):
        """Create stacked pressure graph for BiPAP modes (IPAP + EPAP)"""
        if not daily_metrics:
            return None
        
        try:
            fig, ax = plt.subplots(figsize=(8, 3))
            
            dates = [d['display_date'] for d in daily_metrics]
            ipap_values = [d.get('ipap', 0) for d in daily_metrics]
            epap_values = [d.get('epap', 0) for d in daily_metrics]
            
            x_positions = range(len(dates))
            width = 0.7
            
            # Plot stacked bars
            bars_epap = ax.bar(x_positions, epap_values, width, label='EPAP', 
                              color='#3b82f6', alpha=0.8)
            bars_ipap = ax.bar(x_positions, ipap_values, width, bottom=epap_values, 
                              label='IPAP', color='#f97316', alpha=0.8)
            
            ax.set_xticks(x_positions)
            ax.set_xticklabels(dates, rotation=45, ha='right', fontsize=8)
            
            max_total = max([i + e for i, e in zip(ipap_values, epap_values)]) if ipap_values else 20
            ax.set_ylim(0, max_total + 5)
            ax.set_ylabel('Pressure (cmH₂O)')
            ax.grid(True, linestyle='--', alpha=0.3, axis='y')
            ax.legend(loc='upper right', fontsize=8)
            
            # Add total labels
            for i, (ipap, epap) in enumerate(zip(ipap_values, epap_values)):
                total = ipap + epap
                ax.text(i, total + 0.5, f'{total:.1f}', ha='center', va='bottom', fontsize=7)
            
            plt.tight_layout()
            
            img_buffer = BytesIO()
            plt.savefig(img_buffer, format='PNG', dpi=150, bbox_inches='tight')
            plt.close(fig)
            img_buffer.seek(0)
            
            return Image(img_buffer, width=6.5*inch, height=2.5*inch)
            
        except Exception as e:
            print(f"Error creating BiPAP pressure graph: {e}")
            return None
    
    def create_leak_graph(self, daily_metrics):
        """Create leak graph with threshold line"""
        if not daily_metrics:
            return None
        
        try:
            fig, ax = plt.subplots(figsize=(8, 3))
            
            dates = [d['display_date'] for d in daily_metrics]
            leak_values = [d['leak'] for d in daily_metrics]
            
            colors_list = ['#27ae60' if l <= 24 else '#f39c12' if l <= 50 else '#e74c3c' 
                          for l in leak_values]
            
            x_positions = range(len(dates))
            bars = ax.bar(x_positions, leak_values, color=colors_list, alpha=0.8, width=0.7)
            
            ax.set_xticks(x_positions)
            ax.set_xticklabels(dates, rotation=45, ha='right', fontsize=8)
            
            ax.set_ylim(0, max(leak_values) * 1.2 if leak_values else 100)
            ax.set_ylabel('Leak (L/min)')
            ax.grid(True, linestyle='--', alpha=0.3, axis='y')
            
            # Add threshold line
            ax.axhline(y=24, color='red', linestyle='--', alpha=0.7, label='Threshold (24)')
            ax.legend(loc='upper right', fontsize=8)
            
            for bar, leak in zip(bars, leak_values):
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height + 1,
                       f'{leak:.1f}', ha='center', va='bottom', fontsize=7)
            
            plt.tight_layout()
            
            img_buffer = BytesIO()
            plt.savefig(img_buffer, format='PNG', dpi=150, bbox_inches='tight')
            plt.close(fig)
            img_buffer.seek(0)
            
            return Image(img_buffer, width=6.5*inch, height=2.5*inch)
            
        except Exception as e:
            print(f"Error creating leak graph: {e}")
            return None
    
    def create_tidal_volume_graph(self, daily_metrics):
        """Create tidal volume graph for full BiPAP modes"""
        if not daily_metrics:
            return None
        
        try:
            fig, ax = plt.subplots(figsize=(8, 3))
            
            dates = [d['display_date'] for d in daily_metrics]
            tidal_values = [d.get('tidal_volume', 0) for d in daily_metrics]
            tidal_95_values = [d.get('tidal_volume_95', 0) for d in daily_metrics]
            
            x_positions = range(len(dates))
            width = 0.35
            
            bars_max = ax.bar([i - width/2 for i in x_positions], tidal_values, width, 
                             label='Max (avg)', color='#3b82f6', alpha=0.8)
            bars_95 = ax.bar([i + width/2 for i in x_positions], tidal_95_values, width, 
                            label='95th %', color='#f97316', alpha=0.8)
            
            ax.set_xticks(x_positions)
            ax.set_xticklabels(dates, rotation=45, ha='right', fontsize=8)
            
            max_val = max(tidal_values + tidal_95_values) if (tidal_values + tidal_95_values) else 500
            ax.set_ylim(0, max_val * 1.2)
            ax.set_ylabel('Volume (mL)')
            ax.grid(True, linestyle='--', alpha=0.3, axis='y')
            ax.legend(loc='upper right', fontsize=8)
            
            plt.tight_layout()
            
            img_buffer = BytesIO()
            plt.savefig(img_buffer, format='PNG', dpi=150, bbox_inches='tight')
            plt.close(fig)
            img_buffer.seek(0)
            
            return Image(img_buffer, width=6.5*inch, height=2.5*inch)
            
        except Exception as e:
            print(f"Error creating tidal volume graph: {e}")
            return None
    
    def create_respiratory_rate_graph(self, daily_metrics):
        """Create respiratory rate graph for full BiPAP modes"""
        if not daily_metrics:
            return None
        
        try:
            fig, ax = plt.subplots(figsize=(8, 3))
            
            dates = [d['display_date'] for d in daily_metrics]
            rr_values = [d.get('respiratory_rate', 0) for d in daily_metrics]
            rr_95_values = [d.get('respiratory_rate_95', 0) for d in daily_metrics]
            
            x_positions = range(len(dates))
            width = 0.35
            
            bars_max = ax.bar([i - width/2 for i in x_positions], rr_values, width, 
                             label='Max (avg)', color='#3b82f6', alpha=0.8)
            bars_95 = ax.bar([i + width/2 for i in x_positions], rr_95_values, width, 
                            label='95th %', color='#f97316', alpha=0.8)
            
            ax.set_xticks(x_positions)
            ax.set_xticklabels(dates, rotation=45, ha='right', fontsize=8)
            
            max_val = max(rr_values + rr_95_values) if (rr_values + rr_95_values) else 30
            ax.set_ylim(0, max_val * 1.2)
            ax.set_ylabel('Breaths per Minute')
            ax.grid(True, linestyle='--', alpha=0.3, axis='y')
            ax.legend(loc='upper right', fontsize=8)
            
            plt.tight_layout()
            
            img_buffer = BytesIO()
            plt.savefig(img_buffer, format='PNG', dpi=150, bbox_inches='tight')
            plt.close(fig)
            img_buffer.seek(0)
            
            return Image(img_buffer, width=6.5*inch, height=2.5*inch)
            
        except Exception as e:
            print(f"Error creating respiratory rate graph: {e}")
            return None
    
    def create_minute_ventilation_graph(self, daily_metrics):
        """Create minute ventilation graph for full BiPAP modes"""
        if not daily_metrics:
            return None
        
        try:
            fig, ax = plt.subplots(figsize=(8, 3))
            
            dates = [d['display_date'] for d in daily_metrics]
            mv_values = [d.get('minute_ventilation', 0) for d in daily_metrics]
            mv_95_values = [d.get('minute_ventilation_95', 0) for d in daily_metrics]
            
            x_positions = range(len(dates))
            width = 0.35
            
            bars_max = ax.bar([i - width/2 for i in x_positions], mv_values, width, 
                             label='Max (avg)', color='#3b82f6', alpha=0.8)
            bars_95 = ax.bar([i + width/2 for i in x_positions], mv_95_values, width, 
                            label='95th %', color='#f97316', alpha=0.8)
            
            ax.set_xticks(x_positions)
            ax.set_xticklabels(dates, rotation=45, ha='right', fontsize=8)
            
            max_val = max(mv_values + mv_95_values) if (mv_values + mv_95_values) else 30
            ax.set_ylim(0, max_val * 1.2)
            ax.set_ylabel('Ventilation (L/min)')
            ax.grid(True, linestyle='--', alpha=0.3, axis='y')
            ax.legend(loc='upper right', fontsize=8)
            
            plt.tight_layout()
            
            img_buffer = BytesIO()
            plt.savefig(img_buffer, format='PNG', dpi=150, bbox_inches='tight')
            plt.close(fig)
            img_buffer.seek(0)
            
            return Image(img_buffer, width=6.5*inch, height=2.5*inch)
            
        except Exception as e:
            print(f"Error creating minute ventilation graph: {e}")
            return None


# ==================== UI Widgets ====================

class TherapyReportWidget(QWidget):
    """Widget for displaying Therapy Report section"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        layout.setContentsMargins(0, 0, 0, 0)
        
        title_label = QLabel("Therapy Report")
        title_label.setStyleSheet("""
            font-size: 14px;
            font-weight: bold;
            color: #1e3a8a;
            padding: 5px;
            background: #dbeafe;
            border-radius: 4px;
            border: 1px solid #93c5fd;
        """)
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        
        report_grid = QGridLayout()
        report_grid.setSpacing(8)
        
        serial_label = QLabel("Serial number:")
        serial_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #475569;")
        report_grid.addWidget(serial_label, 0, 0)
        
        self.serial_value = QLabel("")
        self.serial_value.setStyleSheet("font-size: 12px; color: #1e40af;")
        report_grid.addWidget(self.serial_value, 0, 1)
        
        device_label = QLabel("Device:")
        device_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #475569;")
        report_grid.addWidget(device_label, 0, 2)
        
        self.device_value = QLabel("Unknown")
        self.device_value.setStyleSheet("font-size: 12px; color: #1e40af;")
        report_grid.addWidget(self.device_value, 0, 3)
        
        mode_label = QLabel("Mode:")
        mode_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #475569;")
        report_grid.addWidget(mode_label, 0, 4)
        
        self.mode_value = QLabel("Unknown")
        self.mode_value.setStyleSheet("font-size: 12px; color: #1e40af;")
        report_grid.addWidget(self.mode_value, 0, 5)
        
        pressure_label = QLabel("Set Pressure:")
        pressure_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #475569;")
        report_grid.addWidget(pressure_label, 1, 0)
        
        self.pressure_value = QLabel("0.0 cmH₂O")
        self.pressure_value.setStyleSheet("font-size: 12px; color: #1e40af;")
        report_grid.addWidget(self.pressure_value, 1, 1)
        
        flex_label = QLabel("A-Flex:")
        flex_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #475569;")
        report_grid.addWidget(flex_label, 1, 2)
        
        self.flex_value = QLabel("N/A")
        self.flex_value.setStyleSheet("font-size: 12px; color: #1e40af;")
        report_grid.addWidget(self.flex_value, 1, 3)
        
        flex_level_label = QLabel("A-Flex Level:")
        flex_level_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #475569;")
        report_grid.addWidget(flex_level_label, 1, 4)
        
        self.flex_level_value = QLabel("0")
        self.flex_level_value.setStyleSheet("font-size: 12px; color: #1e40af;")
        report_grid.addWidget(self.flex_level_value, 1, 5)
        
        mask_label = QLabel("Mask Type:")
        mask_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #475569;")
        report_grid.addWidget(mask_label, 1, 6)
        
        self.mask_value = QLabel("Unknown")
        self.mask_value.setStyleSheet("font-size: 12px; color: #1e40af;")
        report_grid.addWidget(self.mask_value, 1, 7)
        
        layout.addLayout(report_grid)
        
    def update_values(self, overall_metrics, serial_number=""):
        """Update therapy report values"""
        self.serial_value.setText(serial_number if serial_number else "All Devices")
        self.device_value.setText(overall_metrics.get('device_info', 'Unknown'))
        self.mode_value.setText(overall_metrics.get('mode_name', 'Unknown'))
        self.pressure_value.setText(f"{overall_metrics.get('avg_set_pressure', 0.0):.1f} cmH₂O")
        self.flex_value.setText(overall_metrics.get('flex_info', 'N/A'))
        self.flex_level_value.setText(overall_metrics.get('flex_level', '0'))
        self.mask_value.setText(overall_metrics.get('mask_type', 'Unknown'))


class TherapyEventsWidget(QWidget):
    """Widget for displaying Therapy Events section"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        layout.setContentsMargins(0, 0, 0, 0)
        
        title_label = QLabel("Therapy")
        title_label.setStyleSheet("""
            font-size: 14px;
            font-weight: bold;
            color: #1e3a8a;
            padding: 5px;
            background: #dbeafe;
            border-radius: 4px;
            border: 1px solid #93c5fd;
        """)
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        
        # Create main grid layout
        main_grid = QGridLayout()
        main_grid.setSpacing(8)
        
        # Row 0: Pressure-cmH2O with 4 columns
        pressure_label = QLabel("Pressure-cmH₂O")
        pressure_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #475569;")
        main_grid.addWidget(pressure_label, 0, 0)
        
        median_label = QLabel("Median:")
        median_label.setStyleSheet("font-size: 11px; color: #64748b;")
        main_grid.addWidget(median_label, 0, 1)
        
        self.median_value = QLabel("0.0")
        self.median_value.setStyleSheet("font-size: 12px; font-weight: bold; color: #1e40af;")
        main_grid.addWidget(self.median_value, 0, 2)
        
        percentile_label = QLabel("95th percentile:")
        percentile_label.setStyleSheet("font-size: 11px; color: #64748b;")
        main_grid.addWidget(percentile_label, 0, 3)
        
        self.percentile_value = QLabel("0.0")
        self.percentile_value.setStyleSheet("font-size: 12px; font-weight: bold; color: #1e40af;")
        main_grid.addWidget(self.percentile_value, 0, 4)
        
        maximum_label = QLabel("Maximum:")
        maximum_label.setStyleSheet("font-size: 11px; color: #64748b;")
        main_grid.addWidget(maximum_label, 0, 5)
        
        self.maximum_value = QLabel("0.0")
        self.maximum_value.setStyleSheet("font-size: 12px; font-weight: bold; color: #1e40af;")
        main_grid.addWidget(self.maximum_value, 0, 6)
        
        # Row 1: Events per hour with 4 columns
        events_label = QLabel("Events per hour")
        events_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #475569;")
        main_grid.addWidget(events_label, 1, 0)
        
        ai_label = QLabel("AI:")
        ai_label.setStyleSheet("font-size: 11px; color: #64748b;")
        main_grid.addWidget(ai_label, 1, 1)
        
        self.ai_value = QLabel("0.00")
        self.ai_value.setStyleSheet("font-size: 12px; font-weight: bold; color: #1e40af;")
        main_grid.addWidget(self.ai_value, 1, 2)
        
        hi_label = QLabel("HI:")
        hi_label.setStyleSheet("font-size: 11px; color: #64748b;")
        main_grid.addWidget(hi_label, 1, 3)
        
        self.hi_value = QLabel("0.00")
        self.hi_value.setStyleSheet("font-size: 12px; font-weight: bold; color: #1e40af;")
        main_grid.addWidget(self.hi_value, 1, 4)
        
        ahi_label = QLabel("AHI:")
        ahi_label.setStyleSheet("font-size: 11px; color: #64748b;")
        main_grid.addWidget(ahi_label, 1, 5)
        
        self.ahi_value = QLabel("0.00")
        self.ahi_value.setStyleSheet("font-size: 12px; font-weight: bold; color: #1e40af;")
        main_grid.addWidget(self.ahi_value, 1, 6)
        
        # Row 2: Apnea Index - L/Min with 4 columns
        apnea_label = QLabel("Apnea Index - L/Min")
        apnea_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #475569;")
        main_grid.addWidget(apnea_label, 2, 0)
        
        central_label = QLabel("Central:")
        central_label.setStyleSheet("font-size: 11px; color: #64748b;")
        main_grid.addWidget(central_label, 2, 1)
        
        self.central_value = QLabel("0.00")
        self.central_value.setStyleSheet("font-size: 12px; font-weight: bold; color: #1e40af;")
        main_grid.addWidget(self.central_value, 2, 2)
        
        obstructive_label = QLabel("Obstructive:")
        obstructive_label.setStyleSheet("font-size: 11px; color: #64748b;")
        main_grid.addWidget(obstructive_label, 2, 3)
        
        self.obstructive_value = QLabel("0.00")
        self.obstructive_value.setStyleSheet("font-size: 12px; font-weight: bold; color: #1e40af;")
        main_grid.addWidget(self.obstructive_value, 2, 4)
        
        unknown_label = QLabel("Unknown:")
        unknown_label.setStyleSheet("font-size: 11px; color: #64748b;")
        main_grid.addWidget(unknown_label, 2, 5)
        
        self.unknown_value = QLabel("0.00")
        self.unknown_value.setStyleSheet("font-size: 12px; font-weight: bold; color: #1e40af;")
        main_grid.addWidget(self.unknown_value, 2, 6)
        
        # Row 3: Average Leak - L/Min (single value spanning multiple columns)
        leak_label = QLabel("Average Leak - L/Min")
        leak_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #475569;")
        main_grid.addWidget(leak_label, 3, 0)
        
        self.leak_value = QLabel("0.00")
        self.leak_value.setStyleSheet("font-size: 12px; font-weight: bold; color: #1e40af;")
        main_grid.addWidget(self.leak_value, 3, 1, 1, 6)  # Span 6 columns
        
        layout.addLayout(main_grid)
        
    def update_values(self, overall_metrics):
        """Update therapy event values"""
        if not overall_metrics:
            self.reset_values()
            return
        
        self.median_value.setText(f"{overall_metrics.get('avg_median', 0.0):.1f}")
        self.percentile_value.setText(f"{overall_metrics.get('avg_percentile_95', 0.0):.1f}")
        self.maximum_value.setText(f"{overall_metrics.get('avg_max', 0.0):.1f}")
        
        self.ai_value.setText(f"{overall_metrics.get('avg_apnea', 0.0):.2f}")
        self.hi_value.setText(f"{overall_metrics.get('avg_hypopnea', 0.0):.2f}")
        self.ahi_value.setText(f"{overall_metrics.get('avg_ahi', 0.0):.2f}")
        
        self.central_value.setText(f"{overall_metrics.get('avg_central', 0.0):.2f}")
        self.obstructive_value.setText(f"{overall_metrics.get('avg_obstructive', 0.0):.2f}")
        self.unknown_value.setText("0.00")
        
        self.leak_value.setText(f"{overall_metrics.get('avg_leak', 0.0):.2f}")
    
    def reset_values(self):
        """Reset all values to default"""
        self.median_value.setText("0.0")
        self.percentile_value.setText("0.0")
        self.maximum_value.setText("0.0")
        self.ai_value.setText("0.00")
        self.hi_value.setText("0.00")
        self.ahi_value.setText("0.00")
        self.central_value.setText("0.00")
        self.obstructive_value.setText("0.00")
        self.unknown_value.setText("0.00")
        self.leak_value.setText("0.00")


class Analytics(QWidget):
    """Main Analytics Widget"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        # Removed the line: self.parent = parent  (this was causing the error)
        self.init_ui()
        
        self.reset_data()
        
        QTimer.singleShot(100, self.load_csv_data)
        
    def reset_data(self):
        """Reset all data structures"""
        self.all_sessions = []
        self.serial_data = {}
        self.daily_metrics = []
        self.current_serial = None
        self.filtered_sessions = []
        self.usage_stats_data = {}
        self.overall_metrics = {}
        self.primary_mode = '0'  # Store primary mode for report
        
    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(5)
        main_layout.setContentsMargins(10, 5, 10, 10)

        header_frame = self.create_header_frame()
        main_layout.addWidget(header_frame)

        control_frame = self.create_control_panel()
        main_layout.addWidget(control_frame)

        self.status_label = QLabel("Ready to load data...")
        self.status_label.setStyleSheet("""
            font-size: 12px; 
            font-weight: bold; 
            padding: 8px; 
            border-radius: 5px; 
            background-color: #dbeafe; 
            color: #1e40af;
            border: 1px solid #93c5fd;
            margin-top: 8px;
        """)
        self.status_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.status_label)

        self.therapy_report_widget = TherapyReportWidget()
        main_layout.addWidget(self.therapy_report_widget)

        self.therapy_events_widget = TherapyEventsWidget()
        main_layout.addWidget(self.therapy_events_widget)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane { 
                border: 1px solid #e2e8f0; 
                border-radius: 6px; 
                background: white; 
                margin-top: 8px;
            }
            QTabBar::tab { 
                background: #f1f5f9; 
                padding: 6px 16px; 
                margin-right: 2px; 
                border-radius: 4px; 
                color: #475569; 
                font-weight: bold;
                font-size: 12px;
            }
            QTabBar::tab:selected { 
                background: #3b82f6; 
                color: white; 
            }
            QTabBar::tab:hover { 
                background: #dbeafe; 
            }
        """)
        
        self.usage_tab = self.create_usage_tab()
        self.pressure_tab = self.create_pressure_tab()
        self.leak_tab = self.create_leak_tab()
        self.ahi_tab = self.create_ahi_tab()
        self.detailed_tab = self.create_detailed_tab()
        
        self.tabs.addTab(self.usage_tab, "Usage Hours")
        self.tabs.addTab(self.pressure_tab, "Pressure")
        self.tabs.addTab(self.leak_tab, "Leak")
        self.tabs.addTab(self.ahi_tab, "AHI (Events/hr)")
        self.tabs.addTab(self.detailed_tab, "Detailed Stats")
        
        main_layout.addWidget(self.tabs)

        bottom_frame = self.create_bottom_frame()
        main_layout.addWidget(bottom_frame)

    def create_header_frame(self):
        """Create header frame"""
        header_frame = QFrame()
        header_frame.setStyleSheet("""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                stop:0 #1e3a8a, stop:0.5 #3b82f6, stop:1 #60a5fa);
            border-radius: 12px; 
            padding: 3px;
        """)
        header_layout = QVBoxLayout(header_frame)
        header_layout.setSpacing(2)
        header_layout.setContentsMargins(8, 6, 8, 8)
        
        header = QLabel("CPAP/BiPAP Analytics - Therapy Report System")
        header.setStyleSheet("""
            font-size: 22px; 
            font-weight: bold; 
            color: white; 
            padding: 2px;
        """)
        header.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(header)
        
        info_label = QLabel("Usage Day = Any session > 30min | ≥4h Day = Total daily minutes ≥ 240 | Accurate Pressure Calculations | Mode-specific BiPAP reporting")
        info_label.setStyleSheet("""
            font-size: 11px; 
            color: #dbeafe; 
            padding: 2px;
            font-style: italic;
        """)
        info_label.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(info_label)
        
        return header_frame

    def create_control_panel(self):
        """Create control panel"""
        control_frame = QFrame()
        control_frame.setStyleSheet("""
            background: white; 
            border-radius: 8px; 
            padding: 12px; 
            border: 1px solid #e2e8f0;
        """)
        control_layout = QHBoxLayout(control_frame)
        control_layout.setSpacing(8)
        
        serial_label = QLabel("Serial:")
        serial_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #475569;")
        control_layout.addWidget(serial_label)
        
        self.serial_input = QLineEdit()
        self.serial_input.setPlaceholderText("Enter serial number")
        self.serial_input.setMinimumWidth(120)
        self.serial_input.setStyleSheet("""
            QLineEdit {
                border: 1px solid #cbd5e1;
                border-radius: 5px;
                padding: 6px 8px;
                background: white;
                font-size: 12px;
            }
            QLineEdit:focus {
                border: 1px solid #3b82f6;
                background: #f0f9ff;
            }
        """)
        self.serial_input.returnPressed.connect(self.load_serial_data)
        control_layout.addWidget(self.serial_input)
        
        from_label = QLabel("From:")
        from_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #475569;")
        control_layout.addWidget(from_label)
        
        self.from_date = QDateEdit()
        self.from_date.setCalendarPopup(True)
        self.from_date.setDate(QDate(2025, 8, 1))
        self.from_date.setMaximumWidth(100)
        self.from_date.setStyleSheet("""
            QDateEdit {
                border: 1px solid #cbd5e1;
                border-radius: 5px;
                padding: 5px;
                background: white;
                font-size: 11px;
            }
        """)
        control_layout.addWidget(self.from_date)
        
        to_label = QLabel("To:")
        to_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #475569;")
        control_layout.addWidget(to_label)
        
        self.to_date = QDateEdit()
        self.to_date.setCalendarPopup(True)
        self.to_date.setDate(QDate(2025, 12, 31))
        self.to_date.setMaximumWidth(100)
        self.to_date.setStyleSheet("""
            QDateEdit {
                border: 1px solid #cbd5e1;
                border-radius: 5px;
                padding: 5px;
                background: white;
                font-size: 11px;
            }
        """)
        control_layout.addWidget(self.to_date)
        
        load_btn = self.create_button("Load Serial", "#3b82f6", "#2563eb", "#1d4ed8", 
                                     self.load_serial_data, 80)
        control_layout.addWidget(load_btn)
        
        clear_btn = self.create_button("Clear", "#94a3b8", "#64748b", "#475569", 
                                      self.clear_filters, 70)
        control_layout.addWidget(clear_btn)
        
        control_layout.addStretch()
        return control_frame

    def create_button(self, text, color, hover_color, press_color, callback, min_width=80):
        """Create a styled button"""
        btn = QPushButton(text)
        btn.setMinimumWidth(min_width)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {color};
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 5px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {hover_color}; }}
            QPushButton:pressed {{ background-color: {press_color}; }}
        """)
        btn.clicked.connect(callback)
        return btn

    def create_usage_tab(self):
        """Create usage tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(6)
        
        self.usage_figure = Figure(constrained_layout=True, figsize=(10, 4))
        self.usage_canvas = FigureCanvas(self.usage_figure)
        layout.addWidget(self.usage_canvas)
        
        stats_frame = QFrame()
        stats_frame.setStyleSheet("""
            background: #f8fafc; 
            border-radius: 8px; 
            padding: 12px; 
            border: 1px solid #e2e8f0;
            margin-top: 8px;
        """)
        stats_layout = QHBoxLayout(stats_frame)
        stats_layout.setSpacing(6)
        
        stat_cards = [
            {"title": "Usage days", "value": "0/0 Days (0%)", "color": "#3b82f6", "key": "Usage days"},
            {"title": ">= 4 hours", "value": "0 (0%)", "color": "#10b981", "key": ">= 4 hours"},
            {"title": "< 4 hours", "value": "0 (0%)", "color": "#ef4444", "key": "< 4 hours"},
            {"title": "Usage hours", "value": "00 Hours, 00 Minutes", "color": "#8b5cf6", "key": "Usage hours"},
            {"title": "Avg usage (Total Days)", "value": "00 Hours, 00 Minutes", "color": "#f59e0b", "key": "Average usage (Total Days)"},
            {"title": "Avg usage (Days Used)", "value": "00 Hours, 00 Minutes", "color": "#ec4899", "key": "Average usage (Days Used)"},
            {"title": "Median usage (Days Used)", "value": "00 Hours, 00 Minutes", "color": "#06b6d4", "key": "Median usage (Days Used)"}
        ]
        
        self.usage_stats = {}
        
        for stat in stat_cards:
            card = self.create_usage_stat_card(stat['title'], stat['value'], stat['color'], stat['key'])
            stats_layout.addWidget(card)
        
        layout.addWidget(stats_frame)
        return tab

    def create_usage_stat_card(self, title, value, color, key):
        """Create a usage stat card"""
        card = QFrame()
        card.setStyleSheet("""
            background: white; 
            border-radius: 6px; 
            border: 1px solid #e2e8f0; 
            padding: 6px;
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(2)
        
        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 10px; color: #64748b; font-weight: bold;")
        title_label.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(title_label)
        
        value_label = QLabel(value)
        value_label.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {color};")
        value_label.setAlignment(Qt.AlignCenter)
        value_label.setWordWrap(True)
        card_layout.addWidget(value_label)
        
        self.usage_stats[key] = value_label
        return card

    def create_ahi_tab(self):
        """Create AHI tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(6)
        
        self.ahi_figure = Figure(constrained_layout=True, figsize=(10, 4))
        self.ahi_canvas = FigureCanvas(self.ahi_figure)
        layout.addWidget(self.ahi_canvas)
        
        stats_frame = self.create_ahi_stats_container()
        layout.addWidget(stats_frame)
        return tab

    def create_ahi_stats_container(self):
        """Create AHI statistics container"""
        stats_frame = QFrame()
        stats_frame.setStyleSheet("""
            background: white; 
            border-radius: 8px; 
            padding: 10px; 
            border: 1px solid #e2e8f0;
        """)
        stats_layout = QHBoxLayout(stats_frame)
        stats_layout.setSpacing(8)
        
        self.ahi_stats = {}
        stats_data = [
            ("AHI", "0.00"), ("AI", "0.00"), ("HI", "0.00")
        ]
        
        for key, value in stats_data:
            container = self.create_stat_container(key, value)
            value_label = container.layout().itemAt(1).widget()
            self.ahi_stats[key] = value_label
            stats_layout.addWidget(container)
        
        return stats_frame

    def create_leak_tab(self):
        """Create leak tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(6)
        
        self.leak_figure = Figure(constrained_layout=True, figsize=(10, 4))
        self.leak_canvas = FigureCanvas(self.leak_figure)
        layout.addWidget(self.leak_canvas)
        
        stats_frame = self.create_leak_stats_container()
        layout.addWidget(stats_frame)
        return tab

    def create_leak_stats_container(self):
        """Create leak statistics container"""
        stats_frame = QFrame()
        stats_frame.setStyleSheet("""
            background: white; 
            border-radius: 8px; 
            padding: 10px; 
            border: 1px solid #e2e8f0;
        """)
        stats_layout = QHBoxLayout(stats_frame)
        stats_layout.setSpacing(8)
        
        self.leak_stats = {}
        stats_data = [
            ("Set Threshold", "24.00 L/min"), 
            ("Average Leak", "0.00 L/min"), 
            ("Above Threshold", "0%")
        ]
        
        for key, value in stats_data:
            container = self.create_stat_container(key, value)
            value_label = container.layout().itemAt(1).widget()
            self.leak_stats[key] = value_label
            stats_layout.addWidget(container)
        
        return stats_frame

    def create_pressure_tab(self):
        """Create pressure tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(6)
        
        self.pressure_figure = Figure(constrained_layout=True, figsize=(10, 4))
        self.pressure_canvas = FigureCanvas(self.pressure_figure)
        layout.addWidget(self.pressure_canvas)
        
        stats_frame = self.create_pressure_stats_container()
        layout.addWidget(stats_frame)
        return tab

    def create_pressure_stats_container(self):
        """Create pressure statistics container"""
        stats_frame = QFrame()
        stats_frame.setStyleSheet("""
            background: white; 
            border-radius: 8px; 
            padding: 10px; 
            border: 1px solid #e2e8f0;
        """)
        stats_layout = QHBoxLayout(stats_frame)
        stats_layout.setSpacing(8)
        
        self.pressure_stats = {}
        stats_data = [
            ("Avg Max", "0.00 cmH₂O"), 
            ("Avg Median", "0.00 cmH₂O"), 
            ("Avg 95th %", "0.00 cmH₂O")
        ]
        
        for key, value in stats_data:
            container = self.create_stat_container(key, value)
            value_label = container.layout().itemAt(1).widget()
            self.pressure_stats[key] = value_label
            stats_layout.addWidget(container)
        
        return stats_frame

    def create_stat_container(self, title, value):
        """Create a single stat container"""
        container = QFrame()
        container.setStyleSheet("""
            background: #f8fafc; 
            border-radius: 6px; 
            padding: 8px;
        """)
        c_layout = QVBoxLayout(container)
        c_layout.setSpacing(2)
        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 11px; color: #64748b;")
        title_label.setAlignment(Qt.AlignCenter)
        c_layout.addWidget(title_label)
        value_label = QLabel(value)
        value_label.setStyleSheet("font-size: 11px; font-weight: bold; color: #1e40af;")
        value_label.setAlignment(Qt.AlignCenter)
        value_label.setWordWrap(True)
        c_layout.addWidget(value_label)
        return container

    def create_detailed_tab(self):
        """Create detailed statistics tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(8)
        
        title_label = QLabel("Detailed Statistics")
        title_label.setStyleSheet("""
            font-size: 16px; 
            font-weight: bold; 
            color: #1e3a8a;
            padding: 8px;
        """)
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        
        self.detailed_table = QTableWidget()
        self.detailed_table.setColumnCount(4)
        self.detailed_table.setHorizontalHeaderLabels(["Metric", "Value", "Hours Format", "Decimal Hours"])
        self.detailed_table.setStyleSheet("""
            QTableWidget {
                background: white;
                border: 1px solid #e2e8f0;
                border-radius: 6px;
                font-size: 11px;
            }
            QTableWidget::item {
                padding: 4px;
            }
            QHeaderView::section {
                background: #f1f5f9;
                padding: 6px;
                border: 1px solid #e2e8f0;
                font-weight: bold;
                color: #475569;
            }
        """)
        self.detailed_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.detailed_table)
        
        pressure_frame = QFrame()
        pressure_frame.setStyleSheet("""
            background: #f0f9ff;
            border-radius: 8px;
            padding: 12px;
            border: 1px solid #bae6fd;
            margin-top: 8px;
        """)
        pressure_layout = QVBoxLayout(pressure_frame)
        
        pressure_title = QLabel("Pressure Statistics")
        pressure_title.setStyleSheet("""
            font-size: 14px;
            font-weight: bold;
            color: #0369a1;
            padding: 5px;
        """)
        pressure_title.setAlignment(Qt.AlignCenter)
        pressure_layout.addWidget(pressure_title)
        
        self.stats_table = QTableWidget()
        self.stats_table.setColumnCount(3)
        self.stats_table.setHorizontalHeaderLabels(["Metric", "Value", "Description"])
        self.stats_table.setStyleSheet("""
            QTableWidget {
                background: white;
                border: 1px solid #bae6fd;
                border-radius: 6px;
                font-size: 11px;
            }
            QTableWidget::item {
                padding: 4px;
            }
            QHeaderView::section {
                background: #0ea5e9;
                padding: 6px;
                border: 1px solid #bae6fd;
                font-weight: bold;
                color: white;
            }
        """)
        self.stats_table.horizontalHeader().setStretchLastSection(True)
        pressure_layout.addWidget(self.stats_table)
        
        layout.addWidget(pressure_frame)
        
        severity_frame = QFrame()
        severity_frame.setStyleSheet("""
            background: #f8fafc;
            border-radius: 8px;
            padding: 12px;
            border: 1px solid #e2e8f0;
            margin-top: 8px;
        """)
        severity_layout = QHBoxLayout(severity_frame)
        severity_layout.setSpacing(8)
        
        self.severity_label = QLabel("AHI Severity: Not Calculated")
        self.severity_label.setStyleSheet("""
            font-size: 14px;
            font-weight: bold;
            color: #475569;
            padding: 8px;
            background: white;
            border-radius: 6px;
            border: 1px solid #e2e8f0;
        """)
        self.severity_label.setAlignment(Qt.AlignCenter)
        severity_layout.addWidget(self.severity_label)
        
        layout.addWidget(severity_frame)
        
        return tab

    def create_bottom_frame(self):
        """Create bottom frame with PDF report button"""
        bottom_frame = QFrame()
        bottom_layout = QHBoxLayout(bottom_frame)
        bottom_layout.setSpacing(8)
        
        pdf_report_btn = self.create_button("Generate PDF Report", "#10b981", "#059669", "#047857", 
                                           self.generate_pdf_report, 140)
        bottom_layout.addWidget(pdf_report_btn)
        
        bottom_layout.addStretch()
        return bottom_frame

    def update_therapy_widgets(self, overall_metrics):
        """Update both therapy widgets with calculated metrics"""
        if not overall_metrics:
            self.therapy_report_widget.update_values({}, "")
            self.therapy_events_widget.reset_values()
            return
        
        serial = self.current_serial if self.current_serial else ""
        self.therapy_report_widget.update_values(overall_metrics, serial)
        self.therapy_events_widget.update_values(overall_metrics)

    def parse_csv_data(self, csv_path):
        """Parse CSV file and organize data"""
        try:
            self.reset_data()
            
            if not os.path.exists(csv_path):
                self.show_status(f"File not found: {csv_path}", "error")
                return
            
            with open(csv_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            
            valid_sessions = 0
            
            print(f"\nParsing CSV file: {csv_path}")
            print(f"Total lines: {len(lines)}")
            
            for i, line in enumerate(lines):
                if line.strip() and not line.startswith('#'):
                    session = CPAPCalculations.parse_session_from_csv(line)
                    if session:
                        self.all_sessions.append(session)
                        
                        serial = session['serial_number']
                        if serial not in self.serial_data:
                            self.serial_data[serial] = []
                        self.serial_data[serial].append(session)
                        valid_sessions += 1
            
            print(f"Parsing complete: {valid_sessions} valid sessions")
            print(f"Unique serial numbers: {len(self.serial_data)}")
            
            if not self.all_sessions:
                self.show_status("No valid data found in CSV", "error")
                return
            
            # Keep charts clear until data is loaded for specific serial
            self.filtered_sessions = []
            self.daily_metrics = []
            self.clear_all_charts()
            self.reset_stats_display()
            
            if self.all_sessions:
                dates = [s['therapy_date'] for s in self.all_sessions]
                min_date = min(dates)
                max_date = max(dates)
                self.from_date.setDate(QDate(min_date.year, min_date.month, min_date.day))
                self.to_date.setDate(QDate(max_date.year, max_date.month, max_date.day))
            
            self.show_status(f"CSV loaded with {len(self.all_sessions)} sessions. Enter serial number to view data.", "info")
            
        except Exception as e:
            self.show_status(f"Error loading CSV: {str(e)}", "error")
            print(f"Error: {str(e)}")

    def print_calculation_summary(self):
        """Print calculation summary"""
        if not self.daily_metrics:
            print("\nNo daily metrics available.")
            return
        
        print(f"\nCALCULATION SUMMARY:")
        print(f"{'='*80}")
        print(f"Total days with data: {len(self.daily_metrics)}")
        
        if len(self.daily_metrics) > 0:
            first_day = self.daily_metrics[0]
            print(f"\nSample Day ({first_day['date_str']}):")
            print(f"  Total minutes: {first_day['total_minutes']:.1f}")
            print(f"  Therapy hours: {first_day['therapy_hours']:.1f}")
            print(f"  Sessions: {first_day['sessions_count']}")
            print(f"  Max Pressure (calc): {first_day['max_pressure']:.1f}")
            print(f"  Median Pressure (calc): {first_day['median_pressure']:.1f}")
            print(f"  95th Percentile (calc): {first_day['percentile_95_pressure']:.1f}")
            print(f"  Graph Pressure: {first_day['graph_pressure']:.1f}")
            print(f"  Set Pressure: {first_day['set_pressure']:.1f}")
            print(f"  AHI: {first_day['ahi_index']:.2f}")
            print(f"  AI: {first_day['apnea_index']:.2f}")
            print(f"  HI: {first_day['hypopnea_index']:.2f}")
            print(f"  Central AI: {first_day['central_index']:.2f}")
            print(f"  Obstructive AI: {first_day['obstructive_index']:.2f}")
            print(f"  Leak: {first_day['leak']:.2f}")
            print(f"  Device: {first_day['device_info']}")
            print(f"  Mode: {first_day['mode_name']}")
        
        print(f"{'='*80}")

    def load_csv_file(self):
        """Load CSV file from dialog"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select CSV File",
            "",
            "CSV Files (*.csv);;All Files (*)"
        )
        
        if file_path:
            self.parse_csv_data(file_path)

    def load_serial_data(self):
        """Load data for specific serial number"""
        serial = self.serial_input.text().strip()
        from_date = self.from_date.date().toPyDate()
        to_date = self.to_date.date().toPyDate()
        
        print(f"\nLoading data for Serial: '{serial}', From: {from_date}, To: {to_date}")
        
        if from_date > to_date:
            self.show_status("From date cannot be after To date!", "error")
            return
        
        if not self.all_sessions:
            self.show_status("No CSV data loaded. Please load a CSV file first.", "warning")
            return
        
        filtered_sessions = []
        
        if serial:
            if serial not in self.serial_data:
                self.show_status(f"Serial {serial} not found", "error")
                print(f"Available serials: {list(self.serial_data.keys())}")
                return
            
            self.current_serial = serial
            serial_sessions = self.serial_data[serial]
            
            print(f"Found {len(serial_sessions)} sessions for serial {serial}")
            
            for session in serial_sessions:
                if from_date <= session['therapy_date'] <= to_date:
                    filtered_sessions.append(session)
            
            print(f"After date filtering: {len(filtered_sessions)} sessions")
            
            if not filtered_sessions:
                self.show_status(f"No data for serial {serial} in date range", "warning")
                return
            
        else:
            self.show_status("Please enter a serial number first", "warning")
            return
        
        self.filtered_sessions = filtered_sessions
        self.daily_metrics = CPAPCalculations.calculate_daily_totals(filtered_sessions)
        
        # Determine primary mode for report
        self.primary_mode = DeviceModeProcessor.get_primary_mode(filtered_sessions)
        print(f"Primary mode for report: {self.primary_mode}")
        
        self.update_ui()
        
        usage_stats = CPAPCalculations.calculate_usage_statistics(
            filtered_sessions, from_date, to_date
        )
        
        status = f"Showing {len(filtered_sessions)} sessions, {usage_stats['days_with_usage']} usage days"
        if serial:
            status = f"Serial {serial}: " + status
        self.show_status(status, "success")
        
        self.print_calculation_summary()

    def update_ui(self):
        """Update UI with current data"""
        if not self.daily_metrics:
            self.reset_stats_display()
            self.clear_all_charts()
            return
        
        from_date = self.from_date.date().toPyDate()
        to_date = self.to_date.date().toPyDate()
        
        self.overall_metrics = CPAPCalculations.calculate_overall_metrics(self.daily_metrics)
        
        usage_stats = CPAPCalculations.calculate_usage_statistics(
            self.filtered_sessions, from_date, to_date
        )
        self.usage_stats_data = usage_stats
        
        self.update_usage_statistics_display(usage_stats)
        
        self.ahi_stats['AHI'].setText(f"{self.overall_metrics['avg_ahi']:.2f}")
        self.ahi_stats['AI'].setText(f"{self.overall_metrics['avg_apnea']:.2f}")
        self.ahi_stats['HI'].setText(f"{self.overall_metrics['avg_hypopnea']:.2f}")
        
        self.pressure_stats['Avg Max'].setText(f"{self.overall_metrics['avg_max']:.1f} cmH₂O")
        self.pressure_stats['Avg Median'].setText(f"{self.overall_metrics['avg_median']:.1f} cmH₂O")
        self.pressure_stats['Avg 95th %'].setText(f"{self.overall_metrics['avg_percentile_95']:.1f} cmH₂O")
        
        leak_values = [d['leak'] for d in self.daily_metrics]
        leak_above_threshold = CPAPCalculations.calculate_leak_percentage_above_threshold(leak_values, 24)
        self.leak_stats['Average Leak'].setText(f"{self.overall_metrics['avg_leak']:.2f} L/min")
        self.leak_stats['Above Threshold'].setText(f"{leak_above_threshold:.1f}%")
        
        self.update_therapy_widgets(self.overall_metrics)
        
        self.update_detailed_statistics(self.overall_metrics, usage_stats)
        
        self.update_pressure_statistics_table(self.overall_metrics)
        
        ahi_severity = CPAPCalculations.classify_ahi_severity(self.overall_metrics['avg_ahi'])
        severity_colors = {
            'Normal': '#10b981',
            'Mild': '#f59e0b',
            'Moderate': '#ef4444',
            'Severe': '#dc2626'
        }
        self.severity_label.setText(f"AHI Severity: {ahi_severity} ({self.overall_metrics['avg_ahi']:.2f})")
        self.severity_label.setStyleSheet(f"""
            font-size: 14px;
            font-weight: bold;
            color: white;
            padding: 8px;
            background: {severity_colors.get(ahi_severity, '#475569')};
            border-radius: 6px;
            border: 1px solid #e2e8f0;
        """)
        
        self.update_all_charts()

    def update_usage_statistics_display(self, usage_stats):
        """Update the usage statistics display"""
        if not usage_stats:
            for key in self.usage_stats.keys():
                self.usage_stats[key].setText("0")
            return
        
        self.usage_stats['Usage days'].setText(usage_stats['usage_days'])
        self.usage_stats['>= 4 hours'].setText(usage_stats['greater_than_4'])
        self.usage_stats['< 4 hours'].setText(usage_stats['less_than_4'])
        self.usage_stats['Usage hours'].setText(usage_stats['usage_hours'])
        self.usage_stats['Average usage (Total Days)'].setText(usage_stats['avg_total_days'])
        self.usage_stats['Average usage (Days Used)'].setText(usage_stats['avg_days_used'])
        self.usage_stats['Median usage (Days Used)'].setText(usage_stats['median_days_used'])

    def update_detailed_statistics(self, overall_metrics, usage_stats):
        """Update detailed statistics tab"""
        self.detailed_table.setRowCount(0)
        
        rows = [
            ("Report Duration", f"{usage_stats['report_duration']} days", "-", "-"),
            ("Days with Usage", f"{usage_stats['days_with_usage']} days", "-", "-"),
            ("Days ≥ 4 hours", f"{usage_stats['greater_than_4_count']} days", "-", "-"),
            ("Days < 4 hours", f"{usage_stats['less_than_4_count']} days", "-", "-"),
            ("Usage Hours", usage_stats['usage_hours'], "-", f"{overall_metrics['total_hours']:.2f} hours"),
            ("Avg Usage (Total Days)", usage_stats['avg_total_days'], "-", usage_stats['avg_total_days_decimal']),
            ("Avg Usage (Days Used)", usage_stats['avg_days_used'], "-", usage_stats['avg_days_used_decimal']),
            ("Median Usage (Days Used)", usage_stats['median_days_used'], "-", usage_stats['median_days_used_decimal']),
            ("Total Minutes", f"{usage_stats['total_minutes']:.2f} min", "-", f"{overall_metrics['total_hours']:.2f} hrs"),
            ("Usage Hours (decimal)", f"{overall_metrics['total_hours']:.2f} hrs", "-", f"{overall_metrics['total_hours']:.2f}"),
            ("Avg Hours/Day", f"{overall_metrics['total_hours']/overall_metrics['total_days']:.2f} hrs", "-", f"{overall_metrics['total_hours']/overall_metrics['total_days']:.2f}"),
            ("Avg AHI", f"{overall_metrics['avg_ahi']:.2f}", "-", "-"),
            ("Avg AI", f"{overall_metrics['avg_apnea']:.2f}", "-", "-"),
            ("Avg HI", f"{overall_metrics['avg_hypopnea']:.2f}", "-", "-"),
            ("Avg Central AI", f"{overall_metrics['avg_central']:.2f}", "-", "-"),
            ("Avg Obstructive AI", f"{overall_metrics['avg_obstructive']:.2f}", "-", "-"),
            ("Total Central Events", f"{overall_metrics['total_central']}", "-", "-"),
            ("Total Obstructive Events", f"{overall_metrics['total_obstructive']}", "-", "-"),
            ("Total Hypopnea Events", f"{overall_metrics['total_hypopnea']}", "-", "-"),
            ("Avg Leak", f"{overall_metrics['avg_leak']:.2f} L/min", "-", "-"),
            ("Device", overall_metrics.get('device_info', 'Unknown'), "-", "-"),
            ("Mode", overall_metrics.get('mode_name', 'Unknown'), "-", "-"),
            ("A-Flex", overall_metrics.get('flex_info', 'N/A'), "-", "-"),
            ("A-Flex Level", overall_metrics.get('flex_level', '0'), "-", "-"),
            ("Mask Type", overall_metrics.get('mask_type', 'Unknown'), "-", "-")
        ]
        
        self.detailed_table.setRowCount(len(rows))
        for i, (metric, value, hours_format, decimal_hours) in enumerate(rows):
            self.detailed_table.setItem(i, 0, QTableWidgetItem(metric))
            self.detailed_table.setItem(i, 1, QTableWidgetItem(value))
            self.detailed_table.setItem(i, 2, QTableWidgetItem(hours_format))
            self.detailed_table.setItem(i, 3, QTableWidgetItem(decimal_hours))
        
        self.detailed_table.resizeColumnsToContents()

    def update_pressure_statistics_table(self, overall_metrics):
        """Update pressure statistics table"""
        rows = [
            ("Avg 95th Percentile", f"{overall_metrics.get('avg_percentile_95', 0.0):.1f} cmH₂O", "Average 95th percentile pressure"),
            ("Avg Max Pressure", f"{overall_metrics.get('avg_max', 0.0):.1f} cmH₂O", "Average maximum pressure"),
            ("Avg Median Pressure", f"{overall_metrics.get('avg_median', 0.0):.1f} cmH₂O", "Average median pressure"),
            ("Avg Set Pressure", f"{overall_metrics.get('avg_set_pressure', 0.0):.1f} cmH₂O", "Average set pressure"),
            ("Days", f"{overall_metrics.get('total_days', 0)}", "Total days with data"),
            ("Days ≥4 Hours", f"{self.usage_stats_data.get('greater_than_4_count', 0)}", "Days with ≥4 hours therapy"),
            ("Days <4 Hours", f"{self.usage_stats_data.get('less_than_4_count', 0)}", "Days with <4 hours therapy"),
            ("Device", overall_metrics.get('device_info', 'Unknown'), "Device model"),
            ("Mode", overall_metrics.get('mode_name', 'Unknown'), "Therapy mode"),
            ("A-Flex", overall_metrics.get('flex_info', 'N/A'), "A-Flex setting"),
            ("A-Flex Level", overall_metrics.get('flex_level', 'N/A'), "A-Flex level"),
            ("Mask Type", overall_metrics.get('mask_type', 'Unknown'), "Mask type used"),
        ]
        
        self.stats_table.setRowCount(len(rows))
        
        for i, (metric, value, description) in enumerate(rows):
            self.stats_table.setItem(i, 0, QTableWidgetItem(metric))
            self.stats_table.setItem(i, 1, QTableWidgetItem(value))
            self.stats_table.setItem(i, 2, QTableWidgetItem(description))
        
        self.stats_table.resizeColumnsToContents()

    def reset_stats_display(self):
        """Reset all stats to default values"""
        for key in self.usage_stats.keys():
            self.usage_stats[key].setText("0")
        
        for widget in self.ahi_stats.values():
            widget.setText("0.00")
        
        for widget in self.pressure_stats.values():
            widget.setText("0.00 cmH₂O")
        
        self.leak_stats['Set Threshold'].setText("24.00 L/min")
        self.leak_stats['Average Leak'].setText("0.00 L/min")
        self.leak_stats['Above Threshold'].setText("0%")
        
        self.therapy_report_widget.update_values({})
        self.therapy_events_widget.reset_values()
        
        self.stats_table.setRowCount(0)
        
        self.severity_label.setText("AHI Severity: Not Calculated")
        self.severity_label.setStyleSheet("""
            font-size: 14px;
            font-weight: bold;
            color: #475569;
            padding: 8px;
            background: white;
            border-radius: 6px;
            border: 1px solid #e2e8f0;
        """)
        
        self.detailed_table.setRowCount(0)
        
        self.clear_all_charts()

    def clear_all_charts(self):
        """Clear all charts"""
        figures_to_clear = [
            (self.usage_figure, self.usage_canvas),
            (self.ahi_figure, self.ahi_canvas),
            (self.leak_figure, self.leak_canvas),
            (self.pressure_figure, self.pressure_canvas)
        ]
        
        for fig, canvas in figures_to_clear:
            if fig:
                fig.clear()
                if hasattr(fig, 'add_subplot'):
                    ax = fig.add_subplot(111)
                    ax.text(0.5, 0.5, 'No data available\nPlease enter serial number and click "Load Serial"', 
                          horizontalalignment='center', verticalalignment='center',
                          transform=ax.transAxes, fontsize=12)
                    ax.set_xticks([])
                    ax.set_yticks([])
                    ax.set_frame_on(False)
                if canvas:
                    canvas.draw()

    def clear_filters(self):
        """Clear all filters"""
        self.current_serial = None
        self.serial_input.clear()
        
        if self.all_sessions:
            self.filtered_sessions = []
            self.daily_metrics = []
            self.clear_all_charts()
            self.reset_stats_display()
            self.show_status(f"CSV loaded with {len(self.all_sessions)} sessions. Enter serial number to view data.", "info")

    def show_status(self, message, status_type="info"):
        """Show status message"""
        colors = {
            "success": "#10b981",
            "error": "#ef4444",
            "warning": "#f59e0b",
            "info": "#3b82f6"
        }
        
        self.status_label.setText(message)
        self.status_label.setStyleSheet(f"""
            font-size: 12px; 
            font-weight: bold; 
            padding: 8px; 
            border-radius: 5px; 
            background-color: {colors.get(status_type, '#3b82f6')}20; 
            color: {colors.get(status_type, '#3b82f6')};
            border: 1px solid {colors.get(status_type, '#3b82f6')}40;
        """)

    def update_all_charts(self):
        """Update all charts with mode-specific content"""
        if not self.daily_metrics:
            self.clear_all_charts()
            return
        
        self.update_usage_chart()
        self.update_ahi_chart()
        self.update_leak_chart()
        self.update_pressure_chart()

    def update_usage_chart(self):
        """Update usage chart - Bar graph"""
        self.usage_figure.clear()
        ax = self.usage_figure.add_subplot(111)
        
        if not self.daily_metrics:
            ax.text(0.5, 0.5, 'No data available\nPlease enter serial number and click "Load Serial"', 
                   horizontalalignment='center', verticalalignment='center',
                   transform=ax.transAxes, fontsize=12)
            ax.set_xticks([])
            ax.set_yticks([])
            ax.set_frame_on(False)
            self.usage_canvas.draw()
            return
        
        dates = [d['display_date'] for d in self.daily_metrics]
        usage_hours = [d['therapy_hours'] for d in self.daily_metrics]
        
        bar_colors = ['#10b981' if hours >= 4 else '#ef4444' for hours in usage_hours]
        
        x_positions = range(len(dates))
        bars = ax.bar(x_positions, usage_hours, color=bar_colors, alpha=0.8, width=0.7)
        
        ax.set_xticks(x_positions)
        ax.set_xticklabels(dates, rotation=45, ha='right', fontsize=8)
        
        max_usage = max(usage_hours) if usage_hours else 10
        ax.set_ylim(0, max_usage * 1.2)
        
        ax.set_xlabel("Date", fontsize=12)
        ax.set_ylabel("Usage Hours", fontsize=12)
        ax.grid(True, linestyle='--', alpha=0.3, axis='y')
        
        for i, (bar, hours) in enumerate(zip(bars, usage_hours)):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                   f'{hours:.1f}', ha='center', va='bottom', fontsize=8)
        
        self.usage_canvas.draw()

    def update_ahi_chart(self):
        """Update AHI chart - Stacked bars for BiPAP modes"""
        self.ahi_figure.clear()
        ax = self.ahi_figure.add_subplot(111)
        
        if not self.daily_metrics:
            ax.text(0.5, 0.5, 'No data available\nPlease enter serial number and click "Load Serial"', 
                   horizontalalignment='center', verticalalignment='center',
                   transform=ax.transAxes, fontsize=12)
            ax.set_xticks([])
            ax.set_yticks([])
            ax.set_frame_on(False)
            self.ahi_canvas.draw()
            return
        
        dates = [d['display_date'] for d in self.daily_metrics]
        
        # Check if mode is BiPAP (showing stacked AI+HI)
        mode_str = str(self.primary_mode)
        is_bipap = mode_str in ['5', '05', '7', '07', '8', '08', '9', '09', '11']
        
        if is_bipap:
            # Stacked bar showing AI and HI components
            ai_values = [d['apnea_index'] for d in self.daily_metrics]
            hi_values = [d['hypopnea_index'] for d in self.daily_metrics]
            
            x_positions = range(len(dates))
            
            # Plot stacked bars
            ax.bar(x_positions, ai_values, label='AI', color='#f97316', alpha=0.8, width=0.7)
            ax.bar(x_positions, hi_values, bottom=ai_values, label='HI', color='#3b82f6', alpha=0.8, width=0.7)
            
            # Add total AHI labels
            for i, (ai, hi) in enumerate(zip(ai_values, hi_values)):
                total = ai + hi
                ax.text(i, total + 0.5, f'{total:.1f}', ha='center', va='bottom', fontsize=8)
            
            ax.legend(loc='upper right', fontsize=8)
            
            max_ahi = max([ai + hi for ai, hi in zip(ai_values, hi_values)]) if ai_values else 40
            
        else:
            # Simple AHI bar for CPAP modes
            ahi_values = [d['ahi_index'] for d in self.daily_metrics]
            
            colors_list = []
            for value in ahi_values:
                if value < 5:
                    colors_list.append('#27ae60')
                elif value < 15:
                    colors_list.append('#f39c12')
                elif value < 30:
                    colors_list.append('#e67e22')
                else:
                    colors_list.append('#e74c3c')
            
            x_positions = range(len(dates))
            bars = ax.bar(x_positions, ahi_values, color=colors_list, alpha=0.8, width=0.7)
            
            # Add labels
            for bar, ahi in zip(bars, ahi_values):
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                       f'{ahi:.1f}', ha='center', va='bottom', fontsize=8)
            
            max_ahi = max(ahi_values) if ahi_values else 40
        
        ax.set_xticks(x_positions)
        ax.set_xticklabels(dates, rotation=45, ha='right', fontsize=8)
        
        ax.set_ylim(0, max_ahi * 1.2)
        ax.set_ylabel('Events per Hour', fontsize=12)
        ax.grid(True, linestyle='--', alpha=0.3, axis='y')
        
        # Add severity threshold lines
        ax.axhline(y=5, color='green', linestyle='--', alpha=0.5, label='Normal (<5)')
        ax.axhline(y=15, color='orange', linestyle='--', alpha=0.5, label='Mild (<15)')
        
        self.ahi_canvas.draw()

    def update_leak_chart(self):
        """Update leak chart - Bar graph with threshold line"""
        self.leak_figure.clear()
        ax = self.leak_figure.add_subplot(111)
        
        if not self.daily_metrics:
            ax.text(0.5, 0.5, 'No data available\nPlease enter serial number and click "Load Serial"', 
                   horizontalalignment='center', verticalalignment='center',
                   transform=ax.transAxes, fontsize=12)
            ax.set_xticks([])
            ax.set_yticks([])
            ax.set_frame_on(False)
            self.leak_canvas.draw()
            return
        
        dates = [d['display_date'] for d in self.daily_metrics]
        leak_values = [d['leak'] for d in self.daily_metrics]
        
        leak_colors = []
        for value in leak_values:
            if value <= 24:
                leak_colors.append('#27ae60')
            elif value <= 50:
                leak_colors.append('#f39c12')
            else:
                leak_colors.append('#e74c3c')
        
        x_positions = range(len(dates))
        bars = ax.bar(x_positions, leak_values, color=leak_colors, alpha=0.8, width=0.7)
        
        ax.set_xticks(x_positions)
        ax.set_xticklabels(dates, rotation=45, ha='right', fontsize=8)
        
        max_leak = max(leak_values) if leak_values else 100
        y_max = 100 if max_leak <= 100 else max_leak + 20
        ax.set_ylim(0, y_max)
        
        ax.grid(True, linestyle='--', alpha=0.3, axis='y')
        
        ax.set_xlabel("Date", fontsize=12)
        ax.set_ylabel("Leak Rate (L/min)", fontsize=12)
        
        # Add threshold line
        ax.axhline(y=24, color='red', linestyle='--', alpha=0.7, linewidth=1.5, label='Threshold (24)')
        ax.legend(loc='upper right', fontsize=8)
        
        for i, (bar, leak) in enumerate(zip(bars, leak_values)):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height + 1,
                   f'{leak:.1f}', ha='center', va='bottom', fontsize=8)
        
        self.leak_canvas.draw()

    def update_pressure_chart(self):
        """Update pressure chart - Mode-specific"""
        self.pressure_figure.clear()
        ax = self.pressure_figure.add_subplot(111)
        
        if not self.daily_metrics:
            ax.text(0.5, 0.5, 'No data available\nPlease enter serial number and click "Load Serial"', 
                   horizontalalignment='center', verticalalignment='center',
                   transform=ax.transAxes, fontsize=12)
            ax.set_xticks([])
            ax.set_yticks([])
            ax.set_frame_on(False)
            self.pressure_canvas.draw()
            return
        
        dates = [d['display_date'] for d in self.daily_metrics]
        
        # Check if mode is BiPAP (should show stacked IPAP/EPAP)
        mode_str = str(self.primary_mode)
        is_bipap = mode_str in ['5', '05', '7', '07', '8', '08', '9', '09', '11']
        
        if is_bipap:
            # Stacked bar showing IPAP and EPAP
            ipap_values = [d.get('ipap', d['max_pressure_setting']) for d in self.daily_metrics]
            epap_values = [d.get('epap', d['min_pressure_setting']) for d in self.daily_metrics]
            
            x_positions = range(len(dates))
            width = 0.7
            
            # Plot stacked bars
            ax.bar(x_positions, epap_values, width, label='EPAP', color='#3b82f6', alpha=0.8)
            ax.bar(x_positions, ipap_values, width, bottom=epap_values, label='IPAP', color='#f97316', alpha=0.8)
            
            # Add total labels
            for i, (ipap, epap) in enumerate(zip(ipap_values, epap_values)):
                total = ipap + epap
                ax.text(i, total + 0.5, f'{total:.1f}', ha='center', va='bottom', fontsize=8)
            
            ax.legend(loc='upper right', fontsize=8)
            ax.set_ylabel('Pressure (cmH₂O)', fontsize=12)
            
            max_total = max([i + e for i, e in zip(ipap_values, epap_values)]) if ipap_values else 20
            ax.set_ylim(0, max_total + 5)
            
        else:
            # CPAP modes show 95th percentile
            pressure_values = [d['graph_pressure'] for d in self.daily_metrics]
            
            pressure_colors = []
            for value in pressure_values:
                if value > 20:
                    pressure_colors.append('#F44336')
                elif value > 15:
                    pressure_colors.append('#FF9800')
                else:
                    pressure_colors.append('#2f76cc')
            
            x_positions = range(len(dates))
            bars = ax.bar(x_positions, pressure_values, color=pressure_colors, alpha=0.8, width=0.7)
            
            # Add labels
            for bar, pressure in zip(bars, pressure_values):
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height + 0.2,
                       f'{pressure:.1f}', ha='center', va='bottom', fontsize=8)
            
            ax.set_ylabel('95th Percentile Pressure (cmH₂O)', fontsize=12)
            ax.set_ylim(0, max(pressure_values) * 1.2 if pressure_values else 20)
        
        ax.set_xticks(x_positions)
        ax.set_xticklabels(dates, rotation=45, ha='right', fontsize=8)
        ax.set_xlabel("Date", fontsize=12)
        ax.grid(True, linestyle='--', alpha=0.3, axis='y')
        
        self.pressure_canvas.draw()

    def load_csv_data(self):
        """Load default CSV data"""
        csv_path = "bipapdummy.csv"
        
        if os.path.exists(csv_path):
            self.parse_csv_data(csv_path)
        else:
            self.show_status("Please select a CSV file using File > Open", "info")
            print("No default CSV file found. Please use File > Open to load data.")

    def generate_pdf_report(self):
        """Generate a comprehensive PDF report"""
        try:
            if not self.filtered_sessions:
                self.show_status("No data available to generate report", "warning")
                return
            
            from_date = self.from_date.date().toPyDate()
            to_date = self.to_date.date().toPyDate()
            
            serial = self.current_serial or "All Devices"
            
            print(f"\nGenerating PDF report for Serial: {serial}, From: {from_date}, To: {to_date}")
            print(f"Primary mode: {self.primary_mode}")
            
            # Create report generator instance
            report_gen = ReportGenerator()
            
            success = report_gen.generate_pdf_report(
                sessions=self.filtered_sessions,
                daily_metrics=self.daily_metrics,
                overall_metrics=self.overall_metrics,
                usage_stats=self.usage_stats_data,
                serial=serial,
                from_date=from_date,
                to_date=to_date,
                primary_mode=self.primary_mode
            )

            if success:
                self.show_status("PDF report generated and opened successfully!", "success")
            else:
                self.show_status("Failed to generate PDF report", "error")
                
        except Exception as e:
            self.show_status(f"Error generating PDF report: {str(e)}", "error")
            print(f"Error generating PDF report: {e}")
            import traceback
            traceback.print_exc()


def main():
    """Main application entry point"""
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    app.setApplicationName("CPAP/BiPAP Analytics")
    app.setApplicationVersion("2.0")
    
    analytics = Analytics()
    analytics.setWindowTitle("CPAP/BiPAP Analytics - Therapy Report System")
    analytics.resize(1400, 1000)
    
    # Center the window
    screen_geometry = QApplication.desktop().screenGeometry()
    x = (screen_geometry.width() - analytics.width()) // 2
    y = (screen_geometry.height() - analytics.height()) // 2
    analytics.move(x, y)
    
    analytics.show()
    
    print("\n" + "="*80)
    print("CPAP/BiPAP Analytics - Therapy Report System")
    print("="*80)
    print("Features:")
    print("1. Accurate pressure calculation logic from PHP code")
    print("2. Daily pressure aggregation with multiple sessions")
    print("3. Comprehensive PDF report generation with mode-specific content")
    print("4. Interactive charts and statistics")
    print("5. Therapy Events widget with exact requested layout")
    print("6. Mode-specific BiPAP reporting (CPAP mode vs S/T/VAPS)")
    print("7. AHI/AI/HI calculations with proper aggregation")
    print("8. Apnea Index breakdown (Central/Obstructive/Unknown)")
    print("="*80)
    print("\nApplication started. Use File > Open to load CSV data.")
    
    # Create menu bar
    menubar = analytics.parent().menuBar() if analytics.parent() else None
    if not menubar:
        # Create a simple menu bar
        menubar = QMenuBar()
    
    file_menu = menubar.addMenu("File")
    
    open_action = QAction("Open CSV", analytics)
    open_action.setShortcut("Ctrl+O")
    open_action.triggered.connect(analytics.load_csv_file)
    file_menu.addAction(open_action)
    
    exit_action = QAction("Exit", analytics)
    exit_action.setShortcut("Ctrl+Q")
    exit_action.triggered.connect(app.quit)
    file_menu.addAction(exit_action)
    
    if not analytics.parent():
        # Add menu bar to main window
        main_layout = QVBoxLayout()
        main_layout.setMenuBar(menubar)
        main_layout.addWidget(analytics)
        main_widget = QWidget()
        main_widget.setLayout(main_layout)
        main_window = QMainWindow()
        main_window.setCentralWidget(main_widget)
        main_window.setWindowTitle("CPAP/BiPAP Analytics")
        main_window.resize(1400, 1000)
        main_window.show()
        
        sys.exit(app.exec_())
    else:
        sys.exit(app.exec_())


if __name__ == "__main__":
    main()