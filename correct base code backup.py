import sys, json, os, time, threading
from tkinter.font import Font
import requests  
import re  # Added for safe parsing
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton,
    QStackedWidget, QMessageBox, QFormLayout, QFrame, QHBoxLayout, QDialog,
    QGraphicsOpacityEffect, QGraphicsDropShadowEffect, QSizePolicy, QGridLayout,
    QCalendarWidget, QTableWidget, QTableWidgetItem, QFileDialog, QScrollArea,
    QComboBox, QSpacerItem
)
from PyQt5.QtGui import QColor, QPainter, QPixmap, QFont
from PyQt5.QtCore import Qt, QPropertyAnimation, QEasingCurve, QPoint, QEventLoop, QTimer, pyqtSlot, QRect, pyqtSignal, QObject

# Import AWS IoT related modules
from awscrt import io, mqtt, auth, http
from awsiot import mqtt_connection_builder
from concurrent.futures import Future
import queue  
from datetime import datetime

USER_FILE = "users.json"
# --- THEME COLORS (auto-inserted) ---
THEME_PRIMARY = "#FF6A00"   # orange
THEME_PRIMARY_2 = "#FF8A00"
THEME_BG = "#fbfbfb"
THEME_CARD = "#FFFFFF"
THEME_TEXT = "#111827"
THEME_ACCENT = "#1f6feb"
# End theme block

SETTINGS_FILE = "settings.json"

# -------- Device Status Signal --------
class DeviceStatusSignal(QObject):
    status_changed = pyqtSignal(bool)  # True = connected, False = disconnected

device_status_signal = DeviceStatusSignal()


def load_all_settings() -> dict:
    try:
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def load_users():
    if not os.path.exists(USER_FILE):
        print(f"File {USER_FILE} does not exist, returning empty users")
        return {}
    try:
        with open(USER_FILE, "r") as f:
            users = json.load(f)
            print(f"Loaded users from {USER_FILE}: {users}")
            required_keys = ["name", "contact", "address", "password", "serial_no"]
            for email, data in users.items():
                if not all(key in data for key in required_keys):
                    print(f"Warning: Invalid user data for {email}. Missing keys: {[k for k in required_keys if k not in data]}")
            return users
    except Exception as e:
        print(f"Error loading users from {USER_FILE}: {e}")
        return {}


def save_users(users):
    try:
        with open(USER_FILE, "w") as f:
            json.dump(users, f, indent=4)
            print(f"Saved users to {USER_FILE}: {users}")
    except Exception as e:
        print(f"Error saving users to {USER_FILE}: {e}")
        raise
class OTPDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("OTP Verification")
        self.setFixedSize(400, 250)
        self.setWindowFlags(Qt.Window)

        layout = QVBoxLayout()
        container = QFrame()
        container.setStyleSheet('''
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba(255, 255, 255, 0.95), stop:1 rgba(248, 249, 250, 0.95));
                border-radius: 16px;
                border: 1px solid rgba(52, 152, 219, 0.2);
            }
            QLabel { font-size: 17px; color: #1f2937; }
            QLineEdit { padding: 8px; font-size: 14px; }
            QPushButton { padding: 10px; font-size: 14px; }
        ''')
        container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        vbox = QVBoxLayout()
        vbox.setSpacing(20)
        label = QLabel("Enter OTP (Demo: 123456)")
        label.setAlignment(Qt.AlignCenter)
        self.otp_input = QLineEdit()
        self.otp_input.setPlaceholderText("Enter OTP")
        self.otp_input.setMaxLength(6)
        self.otp_input.setAlignment(Qt.AlignCenter)
        self.otp_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn = QPushButton("Verify OTP")
        btn.clicked.connect(self.verify_otp)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        vbox.addWidget(label)
        vbox.addWidget(self.otp_input)
        vbox.addWidget(btn)
        vbox.addStretch()
        container.setLayout(vbox)
        layout.addWidget(container)
        layout.setContentsMargins(30, 30, 30, 30)
        self.setLayout(layout)

    def verify_otp(self):
        if self.otp_input.text() == "123456":
            QMessageBox.information(self, "Success", "OTP Verified Successfully!")
            self.accept()
        else:
            QMessageBox.warning(self, "Error", "Invalid OTP. Try again.")

# ---------- Main Window ----------
class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BIPAP Dashboard")
        self.setFixedSize(900, 600)
        self.users = load_users()
        self.setWindowFlags(Qt.Window)

        # ---------- Main Layout ----------
        main_layout = QHBoxLayout()
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # Left Panel
        self.left_panel = QFrame()
        self.left_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.left_panel.setStyleSheet("QFrame { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba(52, 73, 94, 0.9), stop:1 rgba(44, 62, 80, 0.9)); border: none; }")

        # Right Panel
        self.right_panel = QFrame()
        self.right_panel.setStyleSheet("QFrame { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba(255, 255, 255, 0.95), stop:1 rgba(248, 249, 250, 0.95)); border-radius: 16px; border: 1px solid rgba(52, 152, 219, 0.2); box-shadow: 0 10px 40px rgba(0, 0, 0, 0.15); }")
        self.right_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(40, 40, 40, 40)
        right_layout.setSpacing(20)
        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.stack.addWidget(self.login_page())
        self.stack.addWidget(self.register_page())
        right_layout.addWidget(self.stack)
        right_layout.addStretch()
        self.right_panel.setLayout(right_layout)

        # Shadow effect
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(25)
        shadow.setXOffset(0)
        shadow.setYOffset(5)
        shadow.setColor(QColor(0, 0, 0, 80))
        self.right_panel.setGraphicsEffect(shadow)

        # Hover animation
        self.right_panel.enterEvent = lambda event: self.hover_card(True)
        self.right_panel.leaveEvent = lambda event: self.hover_card(False)

        main_layout.addWidget(self.left_panel, 1)
        main_layout.addWidget(self.right_panel, 1)
        self.setLayout(main_layout)

        # Fade-in animation
        self.opacity_effect = QGraphicsOpacityEffect()
        self.right_panel.setGraphicsEffect(self.opacity_effect)
        self.anim = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setDuration(1000)
        self.anim.setEasingCurve(QEasingCurve.InOutQuad)
        self.anim.start()

        # Slide-in animation
        self.slide_anim = QPropertyAnimation(self.right_panel, b"pos")
        self.slide_anim.setDuration(1000)
        self.slide_anim.setStartValue(self.right_panel.pos() + QPoint(100, 0))
        self.slide_anim.setEndValue(self.right_panel.pos())
        self.slide_anim.setEasingCurve(QEasingCurve.OutCubic)
        self.slide_anim.start()

    def hover_card(self, hover):
        anim = QPropertyAnimation(self.right_panel, b"geometry")
        anim.setDuration(200)
        rect = self.right_panel.geometry()
        if hover:
            anim.setEndValue(rect.adjusted(-2, -2, 2, 2))
        else:
            anim.setEndValue(rect.adjusted(2, 2, -2, -2))
        anim.setEasingCurve(QEasingCurve.InOutQuad)
        anim.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        bg = QPixmap("C:assets\\sign in background.jpg")
        scaled_bg = bg.scaled(self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        x = (self.width() - scaled_bg.width()) // 2
        y = (self.height() - scaled_bg.height()) // 2
        painter.drawPixmap(x, y, scaled_bg)

    def login_page(self):
        page = QFrame()
        layout = QVBoxLayout()
        layout.setSpacing(20)
        layout.setContentsMargins(0, 0, 0, 0)

        container = QFrame()
        container.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba(255, 255, 255, 0.9), stop:1 rgba(248, 249, 250, 0.9));
                border-radius: 20px;
                border: 1px solid rgba(255, 106, 0, 0.18);
                padding: 30px;
                box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
            }
        """)
        container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        container_layout = QVBoxLayout()
        container_layout.setSpacing(20)
        

        title = QLabel("<h1 style='color:#1f2937; margin:0; font-size:32px; font-family: \"Segoe UI\", sans-serif; font-weight: 700;'>CPAP/BIPAP Dashboard</h1>"
                       "<h2 style='color:#374151; margin:5px 0 0 0; font-size:20px; font-family: \"Segoe UI\", sans-serif; font-weight: 500;'>DeckMount Electronics Ltd.</h2>")
        title.setAlignment(Qt.AlignCenter)

        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("Email ID")
        self.user_input.setStyleSheet(self.input_style())
        self.user_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.user_input.setFixedHeight(50)
        self.pass_input = QLineEdit()
        self.pass_input.setPlaceholderText("Password")
        self.pass_input.setEchoMode(QLineEdit.Password)
        self.pass_input.setStyleSheet(self.input_style())
        self.pass_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.pass_input.setFixedHeight(50)
        login_btn = QPushButton("Login")
        login_btn.setStyleSheet(self.button_style())
        login_btn.clicked.connect(self.do_login)
        login_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        login_btn.setFixedHeight(50)
        #reg_btn = QPushButton("New User? Register Here")
        #reg_btn.setStyleSheet("background:none;color:#1f6feb;border:none;font-size:14px; font-family: \"Segoe UI\", sans-serif; font-weight: 500; text-decoration: underline;")
        #reg_btn.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        #reg_btn.setFixedHeight(30)

        container_layout.addWidget(title)
        container_layout.addWidget(self.user_input)
        container_layout.addWidget(self.pass_input)
        container_layout.addWidget(login_btn)
        #container_layout.addWidget(reg_btn, alignment=Qt.AlignCenter)
        container_layout.addStretch()
        container.setLayout(container_layout)
        layout.addWidget(container)
        
        page.setLayout(layout)
        return page

    def register_page(self):
        page = QFrame()
        main_layout = QVBoxLayout()
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.addStretch()

        container = QFrame()
        container.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba(255, 255, 255, 0.9), stop:1 rgba(248, 249, 250, 0.9));
                border-radius: 20px; 
                border: 1px solid rgba(255, 106, 0, 0.18);
                padding: 30px;
                box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
            }
        """)
        container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        form_layout = QFormLayout()
        form_layout.setVerticalSpacing(15)
        form_layout.setHorizontalSpacing(20)
        form_layout.setLabelAlignment(Qt.AlignRight)

        title = QLabel("<h1 style='color:#1f2937; margin:5px; font-size:28px; font-family: \"Segoe UI\", sans-serif; font-weight: 700;'>New User Registration</h1>")
        title.setAlignment(Qt.AlignCenter)
        form_layout.addRow(title)

        self.name_input = QLineEdit()
        self.contact_input = QLineEdit()
        self.address_input = QLineEdit()
        self.pass_reg_input = QLineEdit()
        self.pass_reg_input.setEchoMode(QLineEdit.Password)
        self.email_input = QLineEdit()
        self.serial_input = QLineEdit()
        for w in [self.name_input, self.contact_input, self.address_input, self.pass_reg_input, self.email_input, self.serial_input]:
            w.setStyleSheet(self.input_style())
            w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            w.setFixedHeight(50)

        form_layout.addRow("Name:", self.name_input)
        form_layout.addRow("Contact:", self.contact_input)
        form_layout.addRow("Address:", self.address_input)
        form_layout.addRow("Password:", self.pass_reg_input)
        form_layout.addRow("Email:", self.email_input)
        form_layout.addRow("Serial No:", self.serial_input)

        reg_btn = QPushButton("Register")
        reg_btn.setStyleSheet(self.button_style())
        reg_btn.clicked.connect(self.register_user)
        reg_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        reg_btn.setFixedHeight(50)
        back_btn = QPushButton("Back to Login")
        back_btn.setStyleSheet("background:none;color:#1f6feb;border:none;font-size:14px; font-family: \"Segoe UI\", sans-serif; font-weight: 500; text-decoration: underline;")
        back_btn.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        back_btn.setFixedHeight(30)
        form_layout.addRow(reg_btn)
        form_layout.addRow(back_btn)

        container.setLayout(form_layout)
        main_layout.addWidget(container, alignment=Qt.AlignCenter)
        main_layout.addStretch()

        page.setLayout(main_layout)
        return page

    def input_style(self):
        return """
        QLineEdit {
            border: 2px solid rgba(255, 106, 0, 0.28);
            border-radius: 14px;
            padding: 12px;
            background: rgba(255, 255, 255, 0.9);
            font-size: 17px;
            font-family: 'Segoe UI', sans-serif;
            color: #1f2937;
        }
        QLineEdit:focus { 
            border: 2px solid #FF6A00; 
            background: rgba(255, 255, 255, 1);
            box-shadow: 0 0 0 3px rgba(255, 106, 0, 0.08);
        }
        QLineEdit::placeholder {
            color: #95a5a6;
        }
        """

    def button_style(self):
        return """
        QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FF6A00, stop:1 #FF8A00);
            color: white; 
            border-radius: 14px; 
            font-weight: 600; 
            padding: 12px;
            font-size: 17px;
            font-family: 'Segoe UI', sans-serif;
            border: none;
        }
        QPushButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FF8A00, stop:1 #FF6A00);
            box-shadow: 0 4px 12px rgba(255, 106, 0, 0.28);
        }
        QPushButton:pressed {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #e55a6f, stop:1 #e8833a);
        }
        """

    def do_login(self):
        email = self.user_input.text().strip()
        pwd = self.pass_input.text().strip()
        print(f"Login attempt: email={email}, password={pwd}, users={self.users}")
        if email == "mehul@admin" and pwd == "admin":
            QMessageBox.information(self, "Success", "Welcome Admin!")
            self.admin_dashboard = AdminDashboard(user_name="Admin", machine_serial="", login_window=self, user_data={})
            self.admin_dashboard.showMaximized()
            self.user_input.clear()
            self.pass_input.clear()
            self.hide()
        elif email in self.users and self.users[email]["password"] == pwd:
            user_name = self.users[email].get("name", email.split('@')[0] or "User")
            serial_no = self.users[email].get('serial_no', 'Unknown')
            user_data = self.users[email]
            user_data['email'] = email
            QMessageBox.information(self, "Success", f"Welcome {user_name}!")
            self.dashboard = Dashboard(user_name=user_name, machine_serial=serial_no, login_window=self, user_data=user_data)
            self.dashboard.showMaximized()
            self.user_input.clear()
            self.pass_input.clear()
            self.hide()
        else:
            QMessageBox.warning(self, "Failed", "Invalid Username or Password")

    def register_user(self):
        name = self.name_input.text().strip()
        contact = self.contact_input.text().strip()
        address = self.address_input.text().strip()
        password = self.pass_reg_input.text().strip()
        email = self.email_input.text().strip()
        serial = self.serial_input.text().strip()
        print(f"Register attempt: email={email}, password={password}")
        if not all([name, contact, address, password, email, serial]):
            QMessageBox.warning(self, "Error", "All fields are required!")
            return
        if email in self.users:
            QMessageBox.warning(self, "Error", "User already exists!")
            return
        
        otp_dialog = OTPDialog(self)
        if otp_dialog.exec_() == QDialog.Accepted:
            try:
                self.users[email] = {
                    "name": name,
                    "contact": contact,
                    "address": address,
                    "password": password,
                    "serial_no": serial
                }
                save_users(self.users)
                self.users = load_users()
                QMessageBox.information(self, "Registered", "User Registered Successfully!")
                self.stack.setCurrentIndex(0)
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to register user: {str(e)}")
                
# -------- Device Status Widget --------
class DeviceStatusIndicator(QFrame):
    """Real-time device connection status indicator"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_connected = False
        self.init_ui()
        
        # Connect to device status signal
        device_status_signal.status_changed.connect(self.update_status)
        
    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignVCenter)
        
        # Status indicator (dot)
        self.indicator_label = QLabel("●")
        self.indicator_label.setAlignment(Qt.AlignVCenter | Qt.AlignHCenter)
        self.indicator_label.setStyleSheet("""
            QLabel {
                color: #e74c3c;
                font-size: 21px;
                font-weight: bold;
                min-width: 36px;
            }
        """)
        
        # Status text
        self.status_label = QLabel("Device Disconnected")
        self.status_label.setAlignment(Qt.AlignVCenter)
        self.status_label.setStyleSheet("""
            QLabel {
                color: #e74c3c;
                font-size: 17px;
                font-weight: 700;
                font-family: 'Segoe UI', sans-serif;
            }
        """)
        
        layout.addWidget(self.indicator_label)
        layout.addWidget(self.status_label)
        layout.addStretch()
        
        self.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ffffff, stop:1 #f5f5f5);
                border-radius: 14px;
                border: 3px solid #d3d3d3;
                padding: 6px;
            }
        """)
    
    def update_status(self, is_connected):
        """Update status display"""
        self.is_connected = is_connected
        
        if is_connected:
            self.indicator_label.setAlignment(Qt.AlignVCenter | Qt.AlignHCenter)
            self.indicator_label.setStyleSheet("""
                QLabel {
                    color: #27ae60;
                    font-size: 26px;
                    font-weight: bold;
                    min-width: 36px;
                }
            """)
            self.status_label.setText("Device Connected")
            self.status_label.setStyleSheet("""
                QLabel {
                    color: #27ae60;
                    font-size: 17px;
                    font-weight: 700;
                    font-family: 'Segoe UI', sans-serif;
                }
            """)
            self.setStyleSheet("""
                QFrame {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #e8f8f0, stop:1 #d5f4e6);
                    border-radius: 14px;
                    border: 3px solid #27ae60;
                    padding: 6px;
                }
            """)
        else:
            self.indicator_label.setAlignment(Qt.AlignVCenter | Qt.AlignHCenter)
            self.indicator_label.setStyleSheet("""
                QLabel {
                    color: #e74c3c;
                    font-size: 22px;
                    font-weight: bold;
                    min-width: 36px;
                }
            """)
            self.status_label.setText("Device Disconnected")
            self.status_label.setStyleSheet("""
                QLabel {
                    color: #e74c3c;
                    font-size: 17px;
                    font-weight: 700;
                    font-family: 'Segoe UI', sans-serif;
                }
            """)
            self.setStyleSheet("""
                QFrame {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #fadbd8, stop:1 #f8d5cd);
                    border-radius: 14px;
                    border: 3px solid #e74c3c;
                    padding: 6px;
                }
            """)

# ---------------- Dashboard ----------------
class Dashboard(QWidget):
    def __init__(self, user_name="Sample User", machine_serial="SN123456", login_window=None, user_data=None):
        super().__init__()
        self.login_window = login_window
        self.user_data = user_data or {}
        self.setWindowTitle("Dashboard")
        self.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #fbfbfb, stop:1 #f6f6f6);
                font-family: 'Segoe UI', sans-serif;
            }
        """)

        self.user_name = user_name
        self.machine_serial = machine_serial
        self.machine_type = "BIPAP"  
        self.start_time = time.time()
        self.therapy_active = True
        self.current_mode = None
        self.current_mode_str = "MANUALMODE"  # Default for CPAP
        self.is_connected = False

        # Default values - 
        self.default_values = {
            "CPAP": {"Set Pressure": 4.0},
            "AutoCPAP": {"Min Pressure": 4.0, "Max Pressure": 20.0},
            "S": {"IPAP": 6.0, "EPAP": 4.0, "Start EPAP": 4.0,
                  "Ti.Min": 0.2, "Ti.Max": 3.0,
                  "Sensitivity": 1.0, "Rise Time": 50.0},
            "T": {"IPAP": 6.0, "EPAP": 4.0, "Start EPAP": 4.0,
                  "Respiratory Rate": 10.0, "Ti.Min": 1.0, "Ti.Max": 2.0, "Sensitivity": 1.0, "Rise Time": 200.0},
            "VAPS": {"Height": 170.0, "Tidal Volume": 500.0, "Max IPAP": 20.0,
                     "Min IPAP": 10.0, "EPAP": 5.0, "Respiratory Rate": 10.0,
                     "Ti.Min": 1.0, "Ti.Max": 2.0, "Rise Time": 200.0, "Sensitivity": 1.0},
            "ST": {"IPAP": 6.0, "EPAP": 4.0, "Start EPAP": 4.0, "Backup Rate": 10.0,
                   "Ti.Min": 1.0, "Ti.Max": 2.0, "Rise Time": 200.0, "Sensitivity": 3.0},
            "Settings": {"IMODE": "OFF", "Leak Alert": "OFF", "Gender": "Male",
                         "Sleep Mode": "OFF", "Mask Type": "Nasal", "Ramp Time": 5.0,
                         "Humidifier": 1.0, "Flex": "OFF", "Flex Level": 1.0}
        }

        self.mode_map = {
            "CPAP": (0, 0),
            "AutoCPAP": (0, 1),
            "S": (1, 2),
            "T": (1, 3),
            "ST": (1, 4),
            "VAPS": (1, 5),
        }

        self.int_fields = {
            "Sensitivity", "Rise Time", "Respiratory Rate", "Backup Rate",
            "Height", "Tidal Volume", "Ramp Time", "Humidifier", "Flex Level"
        }

        self.card_color = "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ffffff, stop:1 #fbfbfb)"
        self.value_labels = {}
        self.info_label = None 
        self.recent_sends = {}  
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)

        # ---------------- Sidebar ----------------
        self.sidebar_frame = QFrame()
        self.sidebar_frame.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Expanding)
        self.sidebar_frame.setMinimumWidth(250)
        self.sidebar_frame.setMaximumWidth(350)
        self.sidebar_frame.setStyleSheet("background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1f2937, stop:1 #374151); border: none; border-radius: 20px 0 0 20px; box-shadow: 5px 0 20px rgba(0, 0, 0, 0.1);")
        sidebar = QVBoxLayout()
        sidebar.setContentsMargins(15, 15, 15, 15)
        sidebar.setSpacing(8)
        self.sidebar_buttons = []
        self.selected_btn = None

        logo = QLabel("CPAP/BIPAP")
        logo.setStyleSheet("color: #ecf0f1; font-size: 22px; font-weight: bold; padding: 10px; font-family: 'Segoe UI', sans-serif;")
        logo.setAlignment(Qt.AlignCenter)
        sidebar.addWidget(logo)

        self.normal_btn_style = """
            QPushButton {
                background: transparent;
                color: #bdc3c7;
                font-weight: 500;
                font-size: 17px;
                text-align: left;
                padding: 12px 15px;
                border-radius: 12px;
                font-family: 'Segoe UI', sans-serif;
                border-left: 4px solid transparent;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(52, 152, 219, 0.2), stop:1 rgba(52, 152, 219, 0.1));
                color: #ffffff;
                border-left: 4px solid #1f6feb;
            }
        """
        self.selected_btn_style = self.normal_btn_style + """
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(52, 152, 219, 0.3), stop:1 rgba(52, 152, 219, 0.2));
                color: #ffffff;
                border-left: 4px solid #1f6feb;
            }
        """
        for text in ["Dashboard", "CPAP Mode", "AutoCPAP Mode", "S Mode", "T Mode", "VAPS Mode", "ST Mode", "Report", "Settings"]:
            btn = QPushButton(text)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setFixedHeight(45)
            btn.setStyleSheet(self.normal_btn_style)
            sidebar.addWidget(btn)
            self.sidebar_buttons.append(btn)

        # Add Logout button
        logout_btn = QPushButton("Logout")
        logout_btn.setFixedHeight(45)
        logout_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        logout_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #e74c3c, stop:1 #c0392b);
                color: #ffffff;
                font-weight: 600;
                font-size: 14px;
                border-radius: 12px;
                padding: 8px;
                font-family: 'Segoe UI', sans-serif;
                border: none;
                box-shadow: 0 4px 12px rgba(231, 76, 60, 0.3);
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #c0392b, stop:1 #a93226);
                box-shadow: 0 6px 16px rgba(231, 76, 60, 0.4);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #a93226, stop:1 #8e2a21);
            }
        """)
        logout_btn.clicked.connect(self.do_logout)
        sidebar.addStretch()
        sidebar.addWidget(logout_btn)
        self.sidebar_frame.setLayout(sidebar)
        main_layout.addWidget(self.sidebar_frame)
        # ---------------- Content ----------------
        content_frame = QFrame()
        content_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        content_layout = QVBoxLayout(content_frame)
        content_layout.setSpacing(12)
        content_layout.setContentsMargins(15, 15, 15, 15)

        # Device Status Indicator (added at top)
        self.device_status = DeviceStatusIndicator()
        self.device_status.setFixedHeight(65)
        self.device_status.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        content_layout.addWidget(self.device_status)

        self.info_label = QLabel(f"User: ({self.user_name})    |    Machine S/N: ({self.machine_serial})")
        self.info_label.setAlignment(Qt.AlignCenter)
        self.info_label.setStyleSheet("font-size: 22px; font-weight: bold; color: #281E5D;")
        self.info_label.setWordWrap(True)
        content_layout.addWidget(self.info_label)

        self.current_mode_label = QLabel("Current Mode: Dashboard")
        self.current_mode_label.setAlignment(Qt.AlignCenter)
        self.current_mode_label.setStyleSheet("font-size: 22px; font-weight: bold; color: #FF6A00; padding: 6px;")
        content_layout.addWidget(self.current_mode_label)

        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        content_layout.addWidget(self.stack)

        # Mode pages
        self.pages = []
        for mode_name in ["Dashboard", "CPAP", "AutoCPAP", "S", "T", "VAPS", "ST", "Report", "Settings"]:
            if mode_name == "Dashboard":
                page = self.create_dashboard_page()
            elif mode_name in self.default_values:
                page = self.create_mode_page(mode_name, self.default_values[mode_name], options_mode=(mode_name == "Settings"))
            else:
                page = self.create_page(f"{mode_name} Page")
            self.pages.append(page)
            self.stack.addWidget(page)

        main_layout.addWidget(self.sidebar_frame, 0)
        main_layout.addWidget(content_frame, 1)  

        # Button actions
        for i, btn in enumerate(self.sidebar_buttons):
            btn.clicked.connect(lambda _, idx=i, name=btn.text(): self.set_mode(idx, name))

        self.update_button_states()
        self.load_settings()
        self.set_mode(0, "Dashboard")

        # Timer for real-time stats
        self.stats_timer = QTimer(self)
        self.stats_timer.timeout.connect(self.update_stats)
        self.stats_timer.start(1000)

        # AWS IoT Integration
        self.aws_send_queue = queue.Queue()
        self.aws_receive_queue = queue.Queue()
        self.aws_thread = threading.Thread(target=self.aws_iot_loop)
        self.aws_thread.daemon = True
        self.aws_thread.start()

    def update_button_states(self):
        active_modes = {
            "CPAP": {"CPAP", "AutoCPAP"},
            "BIPAP": {"CPAP", "AutoCPAP", "S", "T", "ST", "VAPS"}
        }
        active_set = active_modes.get(self.machine_type, {"CPAP", "AutoCPAP", "S", "T", "ST", "VAPS"})

        disabled_style = self.normal_btn_style + f"""
            QPushButton:disabled {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #E0E0E0, stop:1 #CCCCCC);
                color: #AAAAAA;
            }}
        """

        for btn in self.sidebar_buttons:
            btn_text = btn.text().removesuffix(" Mode")
            if btn_text in ["Dashboard", "Report", "Settings"] or btn_text in active_set:
                btn.setEnabled(True)
                btn.setStyleSheet(self.normal_btn_style)
            else:
                btn.setEnabled(False)
                btn.setStyleSheet(disabled_style)

    def get_mode_str(self, mode_name):
        """Generate mode string for CSV based on machine_type and mode_name."""
        if self.machine_type == "CPAP":
            if mode_name == "CPAP":
                return "MANUALMODE"
            elif mode_name == "AutoCPAP":
                return "AUTOMODE"
        else:  
            mode_dict = {
                "CPAP": "CPAPMODE",
                "AutoCPAP": "AUTOMODE",
                "S": "S_MODE",
                "T": "T_MODE",
                "ST": "ST_MODE",
                "VAPS": "VAPS_MODE"
            }
            return mode_dict.get(mode_name, "")
        return ""

    def format_for_csv(self, v):
        if isinstance(v, str):
            try:
                return f"{float(v):.1f}"
            except ValueError:
                return v
        if isinstance(v, (int, float)):
            return f"{float(v):.1f}"
        return str(v)

    def create_dashboard_page(self):
        page = QWidget()
        main_layout = QVBoxLayout(page)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(12, 12, 12, 12)

        card_style = """
            QFrame {
                background-color: #FFFFFF;
                border-radius: 14px;
                border: 1px solid #e0e0e0;
                padding: 15px;
                box-shadow: 0 6px 18px rgba(0,0,0,0.06);
            }
            QLabel {
                font-size: 13px;
                color: #4A4A4A;
                font-family: 'Segoe UI', sans-serif;
                padding: 2px;
            }
        """

        # Patient Information
        patient_frame = QFrame()
        patient_frame.setStyleSheet(card_style)
        patient_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        patient_layout = QFormLayout(patient_frame)
        patient_layout.setLabelAlignment(Qt.AlignRight)
        patient_layout.setFormAlignment(Qt.AlignHCenter)
        patient_layout.setSpacing(8)
        patient_layout.addRow("Serial No:", QLabel(f"({self.user_data.get('serial_no', 'N/A')})"))
        patient_title = QLabel("Patient Information")
        patient_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #ff6a00; margin-bottom: 8px; padding: 2px; font-family: 'Segoe UI', sans-serif;")

        # Stats
        stats_frame = QFrame()
        stats_frame.setStyleSheet(card_style)
        stats_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        stats_layout = QFormLayout(stats_frame)
        stats_layout.setLabelAlignment(Qt.AlignRight)
        stats_layout.setFormAlignment(Qt.AlignHCenter)
        stats_layout.setSpacing(8)
        self.therapy_usage_label = QLabel("(0.0) hours")
        self.machine_up_time_label = QLabel("(0.0) hours")
        stats_layout.addRow("Therapy Usage:", self.therapy_usage_label)
        stats_layout.addRow("Machine Up Time:", self.machine_up_time_label)
        stats_title = QLabel("Usage Stats")
        stats_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #ff6a00; margin-bottom: 8px; padding: 2px; font-family: 'Segoe UI', sans-serif;")

        # Alerts
        alerts_frame = QFrame()
        alerts_frame.setStyleSheet(card_style)
        alerts_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        alerts_layout = QVBoxLayout(alerts_frame)
        alerts_layout.setSpacing(6)
        self.alert_labels = {}
        for setting in ["IMODE", "Leak Alert", "Sleep Mode", "Mask Type", "Ramp Time", "Humidifier"]:
            label = QLabel(f"{setting}: (OFF)")
            label.setWordWrap(True)
            alerts_layout.addWidget(label)
            self.alert_labels[setting] = label
        alerts_title = QLabel("Alerts & Settings")
        alerts_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #ff6a00; margin-bottom: 8px; padding: 2px; font-family: 'Segoe UI', sans-serif;")

        # Report
        report_frame = QFrame()
        report_frame.setStyleSheet(card_style)
        report_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        report_layout = QVBoxLayout(report_frame)
        report_layout.setSpacing(8)
        calendar = QCalendarWidget()
        calendar.setGridVisible(True)
        calendar.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        calendar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        table = QTableWidget(5, 5)
        table.setHorizontalHeaderLabels(["Date", "Usage", "AHI", "Leaks", "Pressure"])
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        for i in range(5):
            for j in range(5):
                table.setItem(i, j, QTableWidgetItem(f"Data {i+1}-{j+1}"))
        pdf_btn = QPushButton("Export PDF")
        pdf_btn.clicked.connect(self.export_pdf)
        pdf_btn.setMinimumHeight(40)
        csv_btn = QPushButton("Export CSV")
        csv_btn.clicked.connect(self.export_csv)
        csv_btn.setMinimumHeight(40)
        btn_layout = QHBoxLayout()
        btn_layout.addWidget(pdf_btn)
        btn_layout.addWidget(csv_btn)
        report_layout.addWidget(calendar)
        report_layout.addWidget(table)
        report_layout.addLayout(btn_layout)
        report_title = QLabel("Report")
        report_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #ff6a00; margin-bottom: 8px; padding: 2px; font-family: 'Segoe UI', sans-serif;")
        calendar.setStyleSheet("""
            QCalendarWidget QToolButton {
                color: black;
                font-size: 14px;
                font-weight: bold;
            }
            QCalendarWidget QToolButton::menu-indicator {
                image: none;
            }
            QCalendarWidget QWidget#qt_calendar_navigationbar {
                background-color: white;
            }
            QCalendarWidget QAbstractItemView {
                color: black;
                selection-background-color: #0078d7;
                selection-color: white;
            }
        """)

        # Grid layout
        grid = QGridLayout()
        grid.setSpacing(15)
        grid.setContentsMargins(0, 0, 0, 0)
        # Row 0: Titles
        grid.addWidget(patient_title, 0, 0)
        grid.addWidget(stats_title, 0, 1)
        grid.addWidget(alerts_title, 0, 2)
        grid.addWidget(report_title, 0, 3)
        # Row 1–2: Main cards
        grid.addWidget(patient_frame, 1, 0, 2, 1)
        grid.addWidget(stats_frame, 1, 1, 2, 1)
        grid.addWidget(alerts_frame, 1, 2, 2, 1)
        grid.addWidget(report_frame, 1, 3, 2, 1)
        # Column stretch
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 2)
        grid.setColumnStretch(2, 2)
        grid.setColumnStretch(3, 3)
        grid.setRowStretch(1, 1)
        grid.setRowStretch(2, 1)
 
        main_layout.addLayout(grid)

        scroll = QScrollArea()
        scroll.setWidget(page)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background: transparent;
            }
            QScrollBar:vertical {
                background: rgba(0,0,0,0.1);
                border-radius: 8px;
                width: 10px;
            }
            QScrollBar::handle:vertical {
                background: #1f6feb;
                border-radius: 5px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background: #ff6a00;
            }
        """)
        return scroll

    def create_mode_page(self, mode_name, defaults, options_mode=False):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(15)
        layout.setContentsMargins(15, 15, 15, 15)

        title = QLabel(mode_name)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 26px; font-weight: 700; color: #1f2937; margin-bottom: 12px; font-family: 'Segoe UI', sans-serif;")
        layout.addWidget(title)

        self.value_labels[mode_name] = {}

        grid = QGridLayout()
        grid.setSpacing(15)
        row, col = 0, 0
        for title, val in defaults.items():
            if options_mode:
                options = []
                if title in ["IMODE", "Leak Alert", "Sleep Mode", "Flex"]:
                    options = ["OFF", "ON"]
                elif title == "Gender":
                    options = ["Male", "Female"]
                elif title == "Mask Type":
                    options = ["Nasal", "Pillow", "FullFace"]
                elif title == "Ramp Time":
                    options = [f"{j}.0" for j in range(5, 46)]
                elif title == "Humidifier":
                    options = [f"{j}.0" for j in range(1, 6)]
                elif title == "Flex Level":
                    options = [f"{j}.0" for j in range(1, 4)]
                card = self.create_option_card(title, val, options)
            else:
                min_val = 4.0 if title in ["Min Pressure", "EPAP", "Start EPAP"] else 0.2 if title in ["Ti.Min"] else 1.0 if title in ["Ti.Max"] else val if val > 0 else 0
                max_val = 20.0 if title in ["Max Pressure", "IPAP", "Max IPAP"] else 3.0 if title in ["Ti.Max"] else val * 10 + 20
                card = self.create_card(title, val, min_val, max_val, mode_name)

            grid.addWidget(card, row, col)
                        # For normal numeric cards → value label is the second QLabel
            # For option cards (Settings) → we still use the second QLabel (not QComboBox)
            value_widget = card.findChildren(QLabel)[1]  # title = [0], value = [1]
            self.value_labels[mode_name][title] = value_widget
            col += 1
            if col > 2:
                col = 0
                row += 1

        layout.addLayout(grid)
        layout.addStretch()

    def update_all_from_cloud(self, message):
        device_data = message.get("device_data")
        if not isinstance(device_data, str):
            QMessageBox.warning(self, "Error", f"Invalid device data: expected string, got {type(device_data)}")
            return

        device_data = device_data.strip()
        if not (device_data.startswith("*") and device_data.endswith("#")):
            QMessageBox.warning(self, "Error", "Device data must start with '*' and end with '#'. ")
            return

        parts = [p.strip() for p in device_data[1:-1].split(",")]

        all_settings = load_all_settings()
        mask_map_inv = {"1.0": "Nasal", "2.0": "Pillow", "3.0": "FullFace"}
        gender_map_inv = {"1.0": "Male", "2.0": "Female"}

        try:
            if self.machine_type == "CPAP":

                # G - CPAP
                g_idx = parts.index("G")
                set_p = float(parts[g_idx + 1])
                all_settings["CPAP"] = {"Set Pressure": set_p}

                # H - AutoCPAP
                h_idx = parts.index("H")
                start_p = float(parts[h_idx + 1])
                min_p = float(parts[h_idx + 2])
                max_p = float(parts[h_idx + 3])
                all_settings["AutoCPAP"] = {"Min Pressure": min_p, "Max Pressure": max_p}

                # I - Settings
                i_idx = parts.index("I")
                ramp = float(parts[i_idx + 1])
                hum = float(parts[i_idx + 2])
                tube = parts[i_idx + 3]
                imode_num = float(parts[i_idx + 4])
                leak_num = float(parts[i_idx + 5])
                gender_num = parts[i_idx + 6]
                sleep_num = float(parts[i_idx + 7])
                key_tube = f"{float(tube):.1f}"
                mask_type = mask_map_inv.get(key_tube, "Nasal")
                imode = "ON" if imode_num == 1.0 else "OFF"
                leak = "ON" if leak_num == 1.0 else "OFF"
                key_gender = f"{float(gender_num):.1f}"
                gender = gender_map_inv.get(key_gender, "Male")
                sleep = "ON" if sleep_num == 1.0 else "OFF"
                serial = parts[i_idx + 8] if i_idx + 8 < len(parts) else ""
                all_settings["Settings"] = {
                    "Ramp Time": ramp,
                    "Humidifier": hum,
                    "Mask Type": mask_type,
                    "IMODE": imode,
                    "Leak Alert": leak,
                    "Gender": gender,
                    "Sleep Mode": sleep
                }
                if serial:
                    self.machine_serial = serial
                    self.info_label.setText(f"User: ({self.user_name})    |    Machine S/N: ({self.machine_serial})")

            else:  # BIPAP
               
                # A - CPAP
                a_idx = parts.index("A")
                set_p = float(parts[a_idx + 1])
                all_settings["CPAP"] = {"Set Pressure": set_p}

                # B - S Mode
                b_idx = parts.index("B")
                ipap = float(parts[b_idx + 1])
                epap = float(parts[b_idx + 2])
                start_epap = float(parts[b_idx + 3])
                ti_min = float(parts[b_idx + 4]) / 10
                ti_max = float(parts[b_idx + 5]) / 10
                sens = float(parts[b_idx + 6])
                rise = float(parts[b_idx + 7])
                all_settings["S"] = {
                    "IPAP": ipap, "EPAP": epap, "Start EPAP": start_epap,
                    "Ti.Min": ti_min, "Ti.Max": ti_max, "Sensitivity": sens, "Rise Time": rise
                }

                # C - T Mode
                c_idx = parts.index("C")
                ipap = float(parts[c_idx + 1])
                epap = float(parts[c_idx + 2])
                start_epap = float(parts[c_idx + 3])
                resp_rate = float(parts[c_idx + 4])
                ti_min = float(parts[c_idx + 5]) / 10
                ti_max = float(parts[c_idx + 6]) / 10
                sens = float(parts[c_idx + 7])
                rise = float(parts[c_idx + 8])
                all_settings["T"] = {
                    "IPAP": ipap, "EPAP": epap, "Start EPAP": start_epap,
                    "Respiratory Rate": resp_rate, "Ti.Min": ti_min, "Ti.Max": ti_max,
                    "Sensitivity": sens, "Rise Time": rise
                }

                # D - ST Mode
                d_idx = parts.index("D")
                ipap = float(parts[d_idx + 1])
                epap = float(parts[d_idx + 2])
                start_epap = float(parts[d_idx + 3])
                backup = float(parts[d_idx + 4])
                ti_min = float(parts[d_idx + 5]) / 10
                ti_max = float(parts[d_idx + 6]) / 10
                sens = float(parts[d_idx + 7])
                rise = float(parts[d_idx + 8])
                all_settings["ST"] = {
                    "IPAP": ipap, "EPAP": epap, "Start EPAP": start_epap,
                    "Backup Rate": backup, "Ti.Min": ti_min, "Ti.Max": ti_max,
                    "Sensitivity": sens, "Rise Time": rise
                }

                # E - VAPS Mode
                e_idx = parts.index("E")
                max_ipap = float(parts[e_idx + 1])
                min_ipap = float(parts[e_idx + 2])
                epap = float(parts[e_idx + 3])
                resp_rate = float(parts[e_idx + 4])
                ti_min = float(parts[e_idx + 5]) / 10
                ti_max = float(parts[e_idx + 6]) / 10
                sens = float(parts[e_idx + 7])
                rise = float(parts[e_idx + 8])
                height = float(parts[e_idx + 10])
                tidal = float(parts[e_idx + 11])
                all_settings["VAPS"] = {
                    "Max IPAP": max_ipap, "Min IPAP": min_ipap, "EPAP": epap,
                    "Respiratory Rate": resp_rate, "Ti.Min": ti_min, "Ti.Max": ti_max,
                    "Sensitivity": sens, "Rise Time": rise, "Height": height, "Tidal Volume": tidal
                }

                # F - Settings
                f_idx = parts.index("F")
                ramp = float(parts[f_idx + 1])
                hum = float(parts[f_idx + 2])
                tube = parts[f_idx + 3]
                imode_num = float(parts[f_idx + 4])
                leak_num = float(parts[f_idx + 5])
                gender_num = parts[f_idx + 6]
                sleep_num = float(parts[f_idx + 7])
                key_tube = f"{float(tube):.1f}"
                mask_type = mask_map_inv.get(key_tube, "Nasal")
                imode = "ON" if imode_num == 1.0 else "OFF"
                leak = "ON" if leak_num == 1.0 else "OFF"
                key_gender = f"{float(gender_num):.1f}"
                gender = gender_map_inv.get(key_gender, "Male")
                sleep = "ON" if sleep_num == 1.0 else "OFF"
                serial = parts[f_idx + 8] if f_idx + 8 < len(parts) else ""
                all_settings["Settings"] = {
                    "Ramp Time": ramp,
                    "Humidifier": hum,
                    "Mask Type": mask_type,
                    "IMODE": imode,
                    "Leak Alert": leak,
                    "Gender": gender,
                    "Sleep Mode": sleep,
                }
                if serial:
                    self.machine_serial = serial
                    self.info_label.setText(f"User: ({self.user_name})    |    Machine S/N: ({self.machine_serial})")
            # Save and load to UI
            with open(SETTINGS_FILE, "w") as f:
                json.dump(all_settings, f, indent=4)
            self.load_settings()
            self.update_alerts()
            self.update_button_states()
            QMessageBox.information(self, "Success", "Settings loaded from cloud into UI!")

        except ValueError as ve:
            QMessageBox.warning(self, "Error", str(ve))
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to parse cloud data: {str(e)}")

    def update_stats(self):
        elapsed = time.time() - self.start_time
        hours = elapsed / 3600
        therapy_hours = hours if self.therapy_active else 0
        self.therapy_usage_label.setText(f"({therapy_hours:.1f}) hours")
        self.machine_up_time_label.setText(f"({hours:.1f}) hours")

    def resizeEvent(self, event):
        """Handle window resize to maintain responsive layout"""
        super().resizeEvent(event)
        width = self.width()
        if width < 1200:
            self.sidebar_frame.setMaximumWidth(200)
        elif width < 1600:
            self.sidebar_frame.setMaximumWidth(280)
        else:
            self.sidebar_frame.setMaximumWidth(350)

    def update_alerts(self):
        self.load_settings()
        if hasattr(self, 'alert_labels'):
            for setting in self.alert_labels:
                value = self.settings.get(setting, self.default_values['Settings'].get(setting, 'OFF'))
                try:
                    fvalue = float(value)
                    disp = f"{fvalue:.1f}"
                except:
                    disp = str(value)
                self.alert_labels[setting].setText(f"{setting}: ({disp})")
                self.alert_labels[setting].setStyleSheet("color: red;" if "Alert" in setting and str(value).upper() == "ON" else "color: green; font-size: calc(12px + 0.02 * 100vw); padding: 2px;")

    def export_pdf(self):
        file_name, _ = QFileDialog.getSaveFileName(self, "Save PDF", "", "PDF Files (*.pdf)")
        if file_name:
            QMessageBox.information(self, "Export", "PDF exported to " + file_name)

    def export_csv(self):
        file_name, _ = QFileDialog.getSaveFileName(self, "Save CSV", "", "CSV Files (*.csv)")
        if file_name:
            QMessageBox.information(self, "Export", "CSV exported to " + file_name)

    def do_logout(self):
        if self.login_window:
            self.login_window.show()
        self.close()

    def set_mode(self, index, name):
        self.stack.setCurrentIndex(index)
        mode_name = name.replace(" Mode", "")
        if mode_name in self.mode_map:
            self.current_mode = mode_name
        self.current_mode_label.setText(f"Current Mode: {name}")
        if name == "Dashboard":
            self.update_alerts()

    def create_page(self, text):
        page = QWidget()
        layout = QVBoxLayout(page)
        label = QLabel(text)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("font-size: 18px; color: #30A8FF; font-weight: bold; padding: 5px;")
        layout.addWidget(label)
        return page

    def create_mode_page(self, mode_name, params, options_mode=False):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)
        layout.setContentsMargins(5, 5, 5, 5)

        grid = QGridLayout()
        grid.setSpacing(10)
        self.value_labels[mode_name] = {}
        row, col = 0, 0

        for i, (title, val) in enumerate(params.items()):
            if options_mode:
                options = []
                numerical_options = False
                if title in ["IMODE", "Leak Alert", "Sleep Mode", "Flex"]:
                    options = ["OFF", "ON"]
                elif title == "Gender":
                    options = ["Male", "Female"]
                elif title == "Mask Type":
                    options = ["Nasal", "Pillow", "FullFace"]
                elif title == "Ramp Time":
                    options = [f"{j}.0" for j in range(5, 46)]
                    numerical_options = True
                elif title == "Humidifier":
                    options = [f"{j}.0" for j in range(1, 6)]
                    numerical_options = True
                elif title == "Flex Level":
                    options = [f"{j}.0" for j in range(1, 4)]
                    numerical_options = True
                card = self.create_option_card(title, val, options)
            else:
                card = self.create_card(title, val, 4.0 if title in ["Min Pressure", "Max Pressure"] else val if val > 0 else 0, 20.0 if title in ["Min Pressure", "Max Pressure"] else val * 10 + 20, mode_name)

            grid.addWidget(card, row, col)
            self.value_labels[mode_name][title] = card.findChildren(QLabel)[1]
            col += 1
            if col > 2:
                col = 0
                row += 1

        layout.addLayout(grid)
        layout.addStretch()

        # Save and Reset buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        btn_layout.setAlignment(Qt.AlignCenter)
        btn_save = QPushButton("Save")
        btn_reset = QPushButton("Reset")

        btn_style = """
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                                            stop:0 #58A6FF, stop:1 #30A8FF);
                color: white;
                font-weight: bold;
                font-size: 14px;
                border-radius: 15px;
                border: 2px solid #1080FF;
                padding: 8px;
            }   
            QPushButton:hover {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                                            stop:0 #30A8FF, stop:1 #58A6FF);
            }
        """
        for btn in [btn_save, btn_reset]:
            btn.setFixedSize(200, 45)    
            btn.setStyleSheet(btn_style)
        @pyqtSlot()
        def on_save_clicked():
            btn_save.setEnabled(False)  
            btn_save.setText("Saving...")  
            self.save_mode(mode_name)
            
            QTimer.singleShot(2000, lambda: (btn_save.setEnabled(True), btn_save.setText("Save")))

        btn_save.clicked.connect(on_save_clicked)
        btn_reset.clicked.connect(lambda: self.reset_mode(mode_name))  

        btn_layout.addWidget(btn_save)
        btn_layout.addWidget(btn_reset)
        layout.addLayout(btn_layout)
        
        return page

    def create_card(self, title, value, min_val, max_val, mode_name):
        unit_map = {
            "IPAP":"CmH2O", "EPAP":"CmH2O", "Start EPAP":"CmH2O",
            "Rise Time":"mSec", "Ti.Min":"Sec", "Ti.Max":"Sec",
            "Ti (Insp. Time)":"Sec", "Height":"cm", "Tidal Volume":"ml",
            "Set Pressure": "CmH2O" if mode_name == "CPAP" else "",
            "Sensitivity": "", "Min IPAP":"CmH2O","Max IPAP":"CmH2O",
            "Min Pressure":"CmH2O", "Max Pressure":"CmH2O", "Backup Rate":"/min",
            "Respiratory Rate":"/min"
        }
        unit = unit_map.get(title, "")

        card = QFrame()
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {self.card_color};
                border-radius: 12px;
                padding: 8px;
            }}
        """)
        main_layout = QHBoxLayout(card)
        main_layout.setSpacing(5)
        main_layout.setContentsMargins(8, 8, 8, 8)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(5)

        label_title = QLabel(title)
        label_title.setAlignment(Qt.AlignCenter)
        label_title.setStyleSheet("font-size: 26px; font-weight: bold; color: #000000; font-family: 'Arial'; padding: 2px;")

        value_label = QLabel(f"({float(value):.1f} {unit})".strip())
        value_label.setAlignment(Qt.AlignCenter)
        value_label.setStyleSheet("font-size: 26px; font-weight: bold; color: #000000; font-family: 'Arial'; padding: 2px;")
        text_layout.addWidget(label_title)
        text_layout.addWidget(value_label)
        text_layout.addStretch()

        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(5)
        btn_layout.setAlignment(Qt.AlignVCenter)

        
        pressure_params = {
            "Set Pressure": 0.2,
            "Min Pressure": 0.2,
            "Max Pressure": 0.2,
            "IPAP": 0.2,
            "EPAP": 0.2,
            "Start EPAP": 0.2,
            "Min IPAP": 0.2,
            "Max IPAP": 0.2
        }
        step = pressure_params.get(title, 0.1 if (max_val - min_val) < 10 else 1)

        # Up Arrow Button
        btn_up = QPushButton("▲")
        btn_up.setFixedSize(60, 35)
        btn_up.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                                            stop:0 #58A6FF, stop:1 #30A8FF);
                color: #FFFFFF;
                font-weight: bold;
                font-size: 17px;
                border-radius: 8px;
                padding: 0px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                                            stop:0 #30A8FF, stop:1 #58A6FF);
            }
        """)

        # Down Arrow Button
        btn_down = QPushButton("▼")
        btn_down.setFixedSize(60, 35)
        btn_down.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                                            stop:0 #58A6FF, stop:1 #30A8FF);
                color: #FFFFFF;
                font-weight: bold;
                font-size: 17px;
                border-radius: 8px;
                padding: 0px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                                            stop:0 #30A8FF, stop:1 #58A6FF);
            }
        """)

        def increase():
            try:
                val_str = value_label.text().strip("() ").split()[0]
                val = float(val_str)
                if val < max_val:
                    val += step
                    value_label.setText(f"({val:.1f} {unit})".strip())
            except:
                pass

        def decrease():
            try:
                val_str = value_label.text().strip("() ").split()[0]
                val = float(val_str)
                if val > min_val:
                    val -= step
                    value_label.setText(f"({val:.1f} {unit})".strip())
            except:
                pass
        btn_up.clicked.connect(increase)
        btn_down.clicked.connect(decrease)

        btn_layout.addWidget(btn_up)
        btn_layout.addWidget(btn_down)

        main_layout.addLayout(text_layout, 2)
        main_layout.addLayout(btn_layout, 1)
        main_layout.addStretch()

        return card

    def create_option_card(self, title, initial, options):
        card = QFrame()
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {self.card_color};
                border-radius: 12px;
                padding: 8px;
            }}
        """)
        main_layout = QHBoxLayout(card)
        main_layout.setSpacing(5)
        main_layout.setContentsMargins(8, 8, 8, 8)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(5)

        label_title = QLabel(title)
        label_title.setAlignment(Qt.AlignCenter)
        label_title.setStyleSheet("font-size: 26px; font-weight: bold; color: #000000; font-family: 'Arial'; padding: 2px;")

        try:
            f_init = float(initial)
            value_label = QLabel(f"({f_init:.1f})")
        except:
            value_label = QLabel(f"({initial})")
        value_label.setAlignment(Qt.AlignCenter)
        value_label.setStyleSheet("font-size: 26px; font-weight: bold; color: #000000; font-family: 'Arial'; padding: 2px;")

        text_layout.addWidget(label_title)
        text_layout.addWidget(value_label)
        text_layout.addStretch()

        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(5)
        btn_layout.setAlignment(Qt.AlignVCenter)

        btn_up = QPushButton("▲")
        btn_up.setFixedSize(60, 35)
        btn_up.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                                            stop:0 #58A6FF, stop:1 #30A8FF);
                color: #FFFFFF;
                font-weight: bold;
                font-size: 22px;
                border-radius: 8px;
                padding: 0px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                                            stop:0 #30A8FF, stop:1 #58A6FF);
            }
        """)

        btn_down = QPushButton("▼")
        btn_down.setFixedSize(60, 35)
        btn_down.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                                            stop:0 #58A6FF, stop:1 #30A8FF);
                color: #FFFFFF;
                font-weight: bold;
                font-size: 22px;
                border-radius: 8px;
                padding: 0px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                                            stop:0 #30A8FF, stop:1 #58A6FF);
            }
        """)

        def increase():
            try:
                current_val = value_label.text().strip("()")
                idx = options.index(current_val)
                idx = (idx + 1) % len(options)
                value_label.setText(f"({options[idx]})")
            except:
                pass
        def decrease():
            try:
                current_val = value_label.text().strip("()")
                idx = options.index(current_val)
                idx = (idx - 1) % len(options)
                value_label.setText(f"({options[idx]})")
            except:
                pass
        btn_up.clicked.connect(increase)
        btn_down.clicked.connect(decrease)

        btn_layout.addWidget(btn_up)
        btn_layout.addWidget(btn_down)

        main_layout.addLayout(text_layout, 2)
        main_layout.addLayout(btn_layout, 1)
        main_layout.addStretch()

        return card
    def save_mode(self, mode_name):
        print("save_mode called") 
        now_time = time.time()
        payload_placeholder = json.dumps({
            "device_status": 1,
            "device_data": f"{mode_name}_{now_time}"
        })
        payload_hash = hash(payload_placeholder)
        last_sent = self.recent_sends.get(payload_hash)
        if last_sent and now_time - last_sent < 30:
            print("Skipping duplicate send (recent)")
            return
      
        self.recent_sends[payload_hash] = now_time
       
        for h, ts in list(self.recent_sends.items()):
            if now_time - ts > 30:
                del self.recent_sends[h]

        mode_data = {}
        for title, label in self.value_labels[mode_name].items():
            raw = label.text().strip("()").split()[0]
            try:
                val = float(raw)
            except ValueError:
                # Regex to extract number from raw (e.g., "0.3s" → 0.3, "0.3 s" → 0.3)
                num_match = re.search(r'[-+]?\d*\.?\d+', raw)
                if num_match:
                    val = float(num_match.group())
                else:
                    val = 0.0  # Fallback to default
            if title in self.int_fields:
                val = int(val)
            mode_data[title] = val 

        # 2. Save to settings.json
        all_settings = load_all_settings()
        all_settings[mode_name] = mode_data
        with open(SETTINGS_FILE, "w") as f:
            json.dump(all_settings, f, indent=4)

        if mode_name == "Settings":
            self.settings = mode_data
            self.update_alerts()

        # 3. Build CSV line based on machine_type
        now = datetime.now()
        date = now.strftime("%d%m%y")
        time_ = now.strftime("%H%M")
        parts = ["*"]
        parts += ["S", date, time_]

        
        if mode_name in ["CPAP", "AutoCPAP", "S", "T", "ST", "VAPS"]:
            mode_str = self.get_mode_str(mode_name)
            parts.append(mode_str)

        mask_map = {"Nasal": "1", "Pillow": "2", "FullFace": "3"}
        gender_map = {"Male": "1", "Female": "2"}
        settings_vals = all_settings.get("Settings", self.default_values["Settings"])
        mask_num = self.format_for_csv(float(mask_map.get(settings_vals.get("Mask Type", "Nasal"), "1")))
        gender_num = self.format_for_csv(float(gender_map.get(settings_vals.get("Gender", "Male"), "1")))

        serial = "12345678,"

        if self.machine_type == "CPAP":
            # G - CPAP
            cpap_vals = all_settings.get("CPAP", self.default_values.get("CPAP", {}))
            set_p = cpap_vals.get("Set Pressure", 4.0)
            parts += ["G", self.format_for_csv(set_p), mask_num]

            # H - AutoCPAP 
            autocpap_vals = all_settings.get("AutoCPAP", self.default_values.get("AutoCPAP", {}))
            min_p = autocpap_vals.get("Min Pressure", 4.0)
            max_p = autocpap_vals.get("Max Pressure", 20.0)
            parts += ["H", self.format_for_csv(min_p), self.format_for_csv(min_p), self.format_for_csv(max_p), mask_num]

            # I - Settings
            ramp = settings_vals.get("Ramp Time", 5.0)
            hum = settings_vals.get("Humidifier", 1.0)
            tube = mask_num  # Assume tubetype = mask
            imode_num = 1.0 if settings_vals.get("IMODE", "OFF").upper() == "ON" else 0.0
            leak_num = 1.0 if settings_vals.get("Leak Alert", "OFF").upper() == "ON" else 0.0
            sleep_num = 1.0 if settings_vals.get("Sleep Mode", "OFF").upper() == "ON" else 0.0
            parts += ["I", self.format_for_csv(ramp), self.format_for_csv(hum), tube, str(imode_num), str(leak_num), gender_num, str(sleep_num), serial]

        else:  # BIPAP
            # A - CPAP
            cpap_vals = all_settings.get("CPAP", self.default_values.get("CPAP", {}))
            set_p = cpap_vals.get("Set Pressure", 4.0)
            parts += ["A", self.format_for_csv(set_p), mask_num]

            # Helper function for safe parsing (used in all loops below)
            def safe_parse_val(v):
                if isinstance(v, str):
                    # Regex to extract number (handles "0.3s", "0.3 s", etc.)
                    num_match = re.search(r'[-+]?\d*\.?\d+', v)
                    if num_match:
                        return float(num_match.group())
                    else:
                        return 0.0  # Fallback
                else:
                    return float(v)  # Ensure float

            # B - S Mode
            s_vals = all_settings.get("S", self.default_values.get("S", {}))
            b_fields = ["IPAP", "EPAP", "Start EPAP", "Ti.Min", "Ti.Max", "Sensitivity", "Rise Time"]
            parts.append("B")
            for f in b_fields:
                v = safe_parse_val(s_vals.get(f, 0.0))
                if f in ("Ti.Min", "Ti.Max"):
                    v = int(v * 10)
                parts.append(self.format_for_csv(v))
            parts.append(mask_num) 

            # C - T Mode
            t_vals = all_settings.get("T", self.default_values.get("T", {}))
            c_fields = ["IPAP", "EPAP", "Start EPAP", "Respiratory Rate", "Ti.Min", "Ti.Max", "Sensitivity", "Rise Time"]
            parts.append("C")
            for f in c_fields:
                v = safe_parse_val(t_vals.get(f, 0.0))
                if f in ("Ti.Min", "Ti.Max"):
                    v = int(v * 10)
                parts.append(self.format_for_csv(v))
            parts.append(mask_num)

            # D - ST Mode
            st_vals = all_settings.get("ST", self.default_values.get("ST", {}))
            d_fields = ["IPAP", "EPAP", "Start EPAP", "Backup Rate", "Ti.Min", "Ti.Max", "Sensitivity", "Rise Time"]
            parts.append("D")
            for f in d_fields: 
                v = safe_parse_val(st_vals.get(f, 0.0))
                if f in ("Ti.Min", "Ti.Max"):
                    v = int(v * 10)
                parts.append(self.format_for_csv(v))
            parts.append(mask_num)

            # E - VAPS Mode
            vaps_vals = all_settings.get("VAPS", self.default_values.get("VAPS", {}))
            e_fields = ["Max IPAP", "Min IPAP", "EPAP", "Respiratory Rate", "Ti.Min", "Ti.Max", "Sensitivity", "Rise Time"]
            parts.append("E")
            for f in e_fields:
                v = safe_parse_val(vaps_vals.get(f, 0.0))
                if f in ("Ti.Min", "Ti.Max"):
                    v = int(v * 10)
                parts.append(self.format_for_csv(v))
            # Height and Tidal Volume (no *10, and after mask_num)
            parts.append(mask_num)
            parts.append(self.format_for_csv(safe_parse_val(vaps_vals.get("Height", 170.0))))
            parts.append(self.format_for_csv(safe_parse_val(vaps_vals.get("Tidal Volume", 500.0))))

            # F - Settings
            ramp = safe_parse_val(settings_vals.get("Ramp Time", 5.0))
            hum = safe_parse_val(settings_vals.get("Humidifier", 1.0))
            tube = mask_num
            imode_num = 1.0 if settings_vals.get("IMODE", "OFF").upper() == "ON" else 0.0
            leak_num = 1.0 if settings_vals.get("Leak Alert", "OFF").upper() == "ON" else 0.0
            sleep_num = 1.0 if settings_vals.get("Sleep Mode", "OFF").upper() == "ON" else 0.0
            parts += ["F", self.format_for_csv(ramp), self.format_for_csv(hum), tube, str(imode_num), str(leak_num), gender_num, str(sleep_num), serial]

        csv_line = ",".join(parts) + "#"

        # 4. Send to AWS
        payload = {
            "device_status": 1,
            "device_data": csv_line
        }
        self.aws_send_queue.put(json.dumps(payload))

        # 5. UI feedback
        changed = {k: mode_data[k] for k in mode_data
                   if all_settings.get(mode_name, {}).get(k) != mode_data[k]}
        changed_list = ", ".join(changed.keys()) if changed else "None"

        preview = csv_line[:200] + "..." if len(csv_line) > 200 else csv_line

        QMessageBox.information(
            self,
            "Settings Saved",
            f"Mode: {mode_name}\n"
            f"Changed fields: {changed_list}\n\n"
            f"Sent CSV line ({self.machine_type} format) to the cloud:\n{preview}"
        )
    def reset_mode(self, mode_name):
        defaults = self.default_values[mode_name]
        for title, label in self.value_labels[mode_name].items():
            val = defaults[title]
            unit_map = {
                "IPAP":"CmH2O", "EPAP":"CmH2O", "Start EPAP":"CmH2O",
                "Rise Time": "mSec", "Ti.Min":"Sec", "Ti.Max":"Sec",
                "Ti (Insp. Time)":"Sec", "Height":"cm", "Tidal Volume":"ml",
                "Set Pressure": "CmH2O" if mode_name == "CPAP" else "",
                "Sensitivity": "", "Min IPAP":"CmH2O", "Max IPAP":"CmH2O",
                "Min Pressure":"CmH2O", "Max Pressure":"CmH2O", "Backup Rate":"/min"
            }
            unit = unit_map.get(title, "")
            try:
                fval = float(val)
                label.setText(f"({fval:.1f} {unit})".strip())
            except:
                label.setText(f"({val} {unit})".strip())
    def load_settings(self):
        try:
            with open(SETTINGS_FILE, "r") as f:
                all_data = json.load(f)
            self.settings = all_data.get("Settings", self.default_values["Settings"])
            for mode, values in all_data.items():
                if mode in self.value_labels:
                    for title, val in values.items():
                        if title in self.value_labels[mode]:
                            unit_map = {
                                "IPAP":"CmH2O", "EPAP":"CmH2O", "Start EPAP":"CmH2O",
                                "Rise Time": "mSec", "Ti.Min":"Sec", "Ti.Max":"Sec",
                                "Ti (Insp. Time)":"Sec", "Height":"cm", "Tidal Volume":"ml",
                                "Set Pressure":"CmH2O" if mode == "CPAP" else "",
                                "Sensitivity": "", "Min IPAP":"CmH2O", "Max IPAP":"CmH2O",
                                "Min Pressure":"CmH2O", "Max Pressure":"CmH2O", "Backup Rate":"/min"
                            }
                            unit = unit_map.get(title, "")
                            try:
                                fval = float(val)
                                self.value_labels[mode][title].setText(f"({fval:.1f} {unit})".strip())
                            except:
                                self.value_labels[mode][title].setText(f"({val} {unit})".strip())
        except FileNotFoundError:
            self.settings = self.default_values["Settings"]

    def aws_iot_loop(self):
        ENDPOINT = "a2jqpfwttlq1yk-ats.iot.us-east-1.amazonaws.com"
        CLIENT_ID = "iotconsole-560333af-04b9-45fb-8cd0-4ef4cd819d92"
        BASE_PATH = r"C:\Users\Divyansh srivastava\Desktop\BIPAP"
        PATH_TO_CERTIFICATE = os.path.join(BASE_PATH, "Aws", "6e5d12437ffc7b19a750505da172d382b6e81026243aa254bce059b8bc45796f-certificate.pem.crt")
        PATH_TO_PRIVATE_KEY = os.path.join(BASE_PATH, "Aws", "6e5d12437ffc7b19a750505da172d382b6e81026243aa254bce059b8bc45796f-private.pem.key")
        PATH_TO_AMAZON_ROOT_CA = os.path.join(BASE_PATH, "Aws", "AmazonRootCA1.pem")

        TOPIC = "esp32/data24"
        ACK_TOPIC = "esp32/data24" 

        QUEUE_FILE = os.path.join(BASE_PATH, "pendingfiles.json")
        pending_messages = []
        is_connected = False
        self.ack_received = True
        pending_send_hold = 5
        connection_time = None
        mqtt_connection = None

        def load_pending():
            nonlocal pending_messages
            try:
                
                if not os.path.exists(QUEUE_FILE):
                    pending_messages = []
                    save_pending()
                    print(f"No pending data file found; initialized empty at {QUEUE_FILE}")
                    return

               
                if os.path.getsize(QUEUE_FILE) == 0:
                    pending_messages = []
                    save_pending()
                    print("Pending file was empty; initialized to empty list.")
                    return

                with open(QUEUE_FILE, 'r', encoding='utf-8') as f:
                    data = f.read().strip()
                    if not data:
                        pending_messages = []
                        save_pending()
                        print("Pending file contained only whitespace; initialized to empty list.")
                        return
                    pending_messages = json.loads(data)
                    if not isinstance(pending_messages, list):
                        pending_messages = [pending_messages]
                        save_pending()
                print(f"Loaded {len(pending_messages)} pending messages from file.")
            except json.JSONDecodeError:
              
                try:
                    corrupt_path = QUEUE_FILE + ".corrupt"
                    os.replace(QUEUE_FILE, corrupt_path)
                    print(f"Corrupt pending file moved to {corrupt_path}; reinitialized.")
                except Exception:
                    print("Failed to backup corrupt pending file; reinitializing in place.")
                pending_messages = []
                save_pending()
            except Exception as e:
                print(f"Error loading pending messages: {e}")
                pending_messages = []

        def save_pending():
            nonlocal pending_messages
            try:
                os.makedirs(os.path.dirname(QUEUE_FILE), exist_ok=True)
                with open(QUEUE_FILE, 'w', encoding='utf-8') as f:
                    json.dump(pending_messages, f, indent=2)
                print("Pending messages saved to file.")
            except Exception as e:
                print(f"Error saving pending messages: {e}")

        def is_duplicate_sample(data):
            nonlocal pending_messages
            for msg in pending_messages:
                if data == msg:
                    return True
            return False

        def on_message_received(topic, payload, dup, qos, retain, **kwargs):
            try:
                print(f"\nReceived message from topic '{topic}':")
                text = payload.decode('utf-8', errors='replace')
           
                try:
                    message = json.loads(text)
                except json.JSONDecodeError:
                    
                    stripped = text.strip()
                    if stripped.startswith("*") and stripped.endswith("#"):
                        message = {"device_status": None, "device_data": stripped}
                    else:
                        
                        message = {"raw_payload": stripped}

                print(f"Message content: {json.dumps(message, indent=2)}")
                if topic == ACK_TOPIC and message.get("acknowledgment") == 1:
                    print("Acknowledgment received")
                    self.ack_received = True
                elif "device_data" in message:
                  
                    if isinstance(message.get("device_data"), str):
                        self.aws_receive_queue.put(message)
                    else:
                        print("Ignored device_data: not a string")
                else:
                 
                    print("Received non-device payload; stored for inspection.")
                print("Message received successfully!")
            except Exception as e:
                print(f"Error processing received message: {e}")

        def on_connection_interrupted(connection, error, **kwargs):
            nonlocal is_connected
            is_connected = False
            self.is_connected = False
            device_status_signal.status_changed.emit(False)  # Emit RED status
            print(f"Connection interrupted. Error: {error}. Device is now DISCONNECTED.")

        def on_connection_resumed(connection, return_code, session_present, **kwargs):
            nonlocal is_connected
            nonlocal connection_time
            is_connected = True
            self.is_connected = True
            device_status_signal.status_changed.emit(True)  # Emit GREEN status
            self.ack_received = True  
            print(f"Connection resumed. Return code: {return_code}, Session present: {session_present}. Device is now CONNECTED.")
            load_pending()
            if not session_present:
                subscribe_to_topics(connection)
            
            connection_time = time.time()
                
        def send_data(data, connection):
            print(f"Publishing message to topic '{TOPIC}':\n{data}")
            try:
                publish_future, packet_id = connection.publish(
                    topic=TOPIC,
                    payload=data.encode('utf-8'),
                    qos=mqtt.QoS.AT_LEAST_ONCE
                )
                publish_future.result(timeout=10)
                print("Data sent to AWS IoT Core! Waiting for acknowledgment...")
                print(f"Packet ID: {packet_id}")
                self.ack_received = False
                return True
            except Exception as e:
                print(f"Publish failed: {e}")
                return False
 
        def send_pending(connection):
            nonlocal pending_messages
            nonlocal connection_time
            print(f"send_pending: ack_received={self.ack_received}, pending_messages_count={len(pending_messages)}")
            if not is_connected:
                print("Cannot send pending messages: Device is DISCONNECTED.")
                return
       
            if connection_time is None or time.time() - connection_time < pending_send_hold:
                print(f"Deferring pending sends for {pending_send_hold} seconds after connect...")
                return
            if pending_messages and self.ack_received:
                data = pending_messages[0]
                print(f"Attempting to send pending message: {data}")
                if send_data(data, connection):
                    start_time = time.time()
                    while not self.ack_received and time.time() - start_time < 10:
                        time.sleep(0.1)
                    if self.ack_received:
                        print("Message acknowledged, removing from queue")
                        pending_messages.pop(0)
                        save_pending()
                    else:
                        print("No acknowledgment received within timeout. Proceeding to next message (fallback).")
                        pending_messages.pop(0)
                else:
                    print("Failed to send pending message.")

        def subscribe_to_topics(connection):
            nonlocal is_connected
            if not is_connected:
                print("Cannot subscribe: Device is DISCONNECTED.")
                return False
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    print(f"Subscribing to topic '{TOPIC}' (attempt {attempt + 1})...")
                    subscribe_future, packet_id = connection.subscribe(
                        topic=TOPIC,
                        qos=mqtt.QoS.AT_LEAST_ONCE,
                        callback=on_message_received
                    )
                    subscribe_result = subscribe_future.result(timeout=10)
                    print(f"Subscribed to topic '{TOPIC}' with QoS: {subscribe_result['qos']}")
                    print(f"Subscription packet ID: {packet_id}")

                    print(f"Subscribing to acknowledgment topic '{ACK_TOPIC}' (attempt {attempt + 1})...")
                    subscribe_future, packet_id = connection.subscribe(
                        topic=ACK_TOPIC,
                        qos=mqtt.QoS.AT_LEAST_ONCE,
                        callback=on_message_received
                    )
                    subscribe_result = subscribe_future.result(timeout=10)
                    print(f"Subscribed to topic '{ACK_TOPIC}' with QoS: {subscribe_result['qos']}")
                    print(f"Subscription packet ID: {packet_id}")
                    return True
                except Exception as e:
                    print(f"Subscription failed: {e}. Retrying..." if attempt < max_retries - 1 else f"Subscription failed after {max_retries} attempts: {e}")
                    time.sleep(1)
            return False

        io.init_logging(io.LogLevel.Error, 'stderr')
        event_loop_group = io.EventLoopGroup(1)
        host_resolver = io.DefaultHostResolver(event_loop_group)
        client_bootstrap = io.ClientBootstrap(event_loop_group, host_resolver)

        
        missing_files = [p for p in (PATH_TO_CERTIFICATE, PATH_TO_PRIVATE_KEY, PATH_TO_AMAZON_ROOT_CA) if not os.path.isfile(p)]
        if missing_files:
            
            alt_base = os.path.join(os.getcwd(), 'Aws')
            alt_paths = [os.path.join(alt_base, os.path.basename(p)) for p in (PATH_TO_CERTIFICATE, PATH_TO_PRIVATE_KEY, PATH_TO_AMAZON_ROOT_CA)]
            if all(os.path.isfile(p) for p in alt_paths):
                PATH_TO_CERTIFICATE, PATH_TO_PRIVATE_KEY, PATH_TO_AMAZON_ROOT_CA = alt_paths
                print("Found TLS files in local 'Aws' folder; updated paths.")
            else:
                print(f"MQTT TLS files missing: {missing_files}. Aborting AWS IoT connection loop.")
                return

        mqtt_connection = mqtt_connection_builder.mtls_from_path(
            endpoint=ENDPOINT,
            cert_filepath=PATH_TO_CERTIFICATE,
            pri_key_filepath=PATH_TO_PRIVATE_KEY,
            client_bootstrap=client_bootstrap,
            ca_filepath=PATH_TO_AMAZON_ROOT_CA,
            on_connection_interrupted=on_connection_interrupted,
            on_connection_resumed=on_connection_resumed,
            client_id=CLIENT_ID,
            clean_session=False,
            keep_alive_secs=30
        )
        load_pending()
        while not is_connected:
            print(f"Connecting to {ENDPOINT} with client ID '{CLIENT_ID}'...")
            try:
                connect_future: Future = mqtt_connection.connect()
                connect_future.result(timeout=10)
                is_connected = True
                self.is_connected = True
                connection_time = time.time()
                device_status_signal.status_changed.emit(True)  # Emit GREEN status on first connect
                print("Connected successfully to AWS IoT Core! Device is now CONNECTED.")
                subscribe_to_topics(mqtt_connection)
                
            except Exception as e:
                print(f"Connection failed: {e}. Device is DISCONNECTED. Retrying in 1 second...")
                time.sleep(1)

        try:
            print("\nKeeping connection alive to receive messages and check for pending data...")
            while True:
                print(f"Device connection status: {'CONNECTED' if is_connected else 'DISCONNECTED'}")
                if is_connected:
                    if pending_messages and self.ack_received:
                        send_pending(mqtt_connection)
                    try:
                        new_data = self.aws_send_queue.get_nowait()
                        if not is_duplicate_sample(new_data):
                            if not send_data(new_data, mqtt_connection):
                                pending_messages.append(new_data)
                                save_pending()
                    except queue.Empty:
                        pass
                else:
                    print("Attempting to reconnect...")
                    try:
                        connect_future: Future = mqtt_connection.connect()
                        connect_future.result(timeout=10)
                        is_connected = True 
                        print("Reconnected successfully to AWS IoT Core! Device is now CONNECTED.")
                        subscribe_to_topics(mqtt_connection)
                        send_pending(mqtt_connection)
                    except Exception as e:
                        print(f"Reconnection failed: {e}. Retrying in 1 second...")
                    try:
                        new_data = self.aws_send_queue.get_nowait()
                        if not is_duplicate_sample(new_data):
                            pending_messages.append(new_data)
                            save_pending()
                        print("New data queued to pending_data.json since device is DISCONNECTED.")
                    except queue.Empty: 
                        pass
                time.sleep(2 if not is_connected else 1)
        except KeyboardInterrupt:
            print("\nDisconnecting from AWS IoT Core...")

class AdminDashboard(Dashboard):
    def __init__(self, user_name="Admin", machine_serial="", login_window=None, user_data={}):
        super().__init__(user_name, machine_serial, login_window, user_data)
        self.machine_type_combo.currentTextChanged.connect(self.on_type_change)
        self.machine_serial = machine_serial

    def create_dashboard_page(self):
        page = QWidget()
        main_layout = QVBoxLayout(page)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(15, 15, 15, 15)

        card_style = """
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ffffff, stop:1 #fbfbfb);
                border-radius: 16px;
                border: none;
                padding: 20px;
                box-shadow: 0 8px 28px rgba(0,0,0,0.08);
            }
            QLabel {
                font-size: 14px;
                color: #5a6c7d;
                font-family: 'Segoe UI', sans-serif;
                padding: 4px;
                font-weight: 500;
            }
        """

        # Admin Controls
        patient_frame = QFrame()
        patient_frame.setStyleSheet(card_style)
        patient_frame.setMinimumSize(150, 100)
        patient_layout = QFormLayout(patient_frame)
        patient_layout.setLabelAlignment(Qt.AlignRight)
        patient_layout.setFormAlignment(Qt.AlignHCenter)
        patient_layout.setSpacing(12)
        patient_layout.setContentsMargins(15, 15, 15, 15)
        
        # === Serial No ===
        serial_label = QLabel("Serial No:")
        serial_label.setStyleSheet("font-size: 17px; font-weight: 500; color: #1f2937; font-family: 'Segoe UI', sans-serif;")
        
        self.serial_input = QLineEdit(self.machine_serial)
        self.serial_input.setPlaceholderText("Enter Machine Serial Number")
        self.serial_input.setFixedHeight(50)
        self.serial_input.setMinimumWidth(150)
        self.serial_input.setMaxLength(20)
        self.serial_input.setStyleSheet("""
            QLineEdit {
                border: 2px solid rgba(52, 152, 219, 0.3);
                border-radius: 14px;
                padding: 12px 16px;
                background: rgba(255, 255, 255, 0.95);
                font-size: 14px;
                font-weight: 500;
                font-family: 'Segoe UI', sans-serif;
                color: #1f2937;
            }
            QLineEdit:focus {
                border: 2px solid #1f6feb;
                background: white;
                box-shadow: 0 0 0 3px rgba(52, 152, 219, 0.15);
            }
            QLineEdit::placeholder {
                color: #95a5a6;
            }
        """)
        
        patient_layout.addRow(serial_label, self.serial_input)
        
        # === Spacer ===
        spacer = QFrame()
        spacer.setFixedHeight(2) # Increased gap
        patient_layout.addRow("", spacer)
        
        # === Machine Type ===
        type_label = QLabel("Machine Type:")
        type_label.setStyleSheet("font-size: 14px; font-weight: 600; color: #1f2937; font-family: 'Segoe UI', sans-serif;")
        
        self.machine_type_combo = QComboBox()
        self.machine_type_combo.addItems(["CPAP", "BIPAP"])
        self.machine_type_combo.setCurrentText("BIPAP")
        self.machine_type_combo.setFixedHeight(50)
        self.machine_type_combo.setStyleSheet("""
            QComboBox {
                border: 2px solid rgba(52, 152, 219, 0.3);
                border-radius: 14px;
                padding: 10px 16px;
                background: white;
                font-size: 14px;
                font-weight: 500;
                font-family: 'Segoe UI', sans-serif;
            }
            QComboBox:focus {
                border: 2px solid #1f6feb;
                box-shadow: 0 0 0 3px rgba(52, 152, 219, 0.15);
            }
            QComboBox::drop-down {
                border: none;
                width: 30px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 8px solid #1f6feb;
                margin-right: 10px;
            }
        """)
        
        patient_layout.addRow(type_label, self.machine_type_combo)
        
        # === Spacer before button ===
        spacer2 = QFrame()
        spacer2.setFixedHeight(2)  
        patient_layout.addRow("", spacer2)
        
        # === Fetch Settings Button ===
        fetch_btn = QPushButton("Fetch Settings")
        fetch_btn.clicked.connect(self.fetch_settings)
        fetch_btn.setFixedHeight(50)
        fetch_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #9b59b6, stop:1 #8e44ad);
                color: white;
                border-radius: 14px;
                padding: 14px 28px;
                font-weight: 600;
                font-size: 14px;
                font-family: 'Segoe UI', sans-serif;
                border: none;
                min-width: 110px;
                margin-top: 10px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #8e44ad, stop:1 #9b59b6);
                box-shadow: 0 4px 15px rgba(155, 89, 182, 0.4);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #7d3c98, stop:1 #6c3483);
                box-shadow: 0 2px 8px rgba(155, 89, 182, 0.3);
            }
        """)
        
        # Create a separate layout for the button to center it
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(fetch_btn)
        button_layout.addStretch()
        
        patient_layout.addRow("", button_layout)
        
        patient_title = QLabel("Admin Controls")
        patient_title.setStyleSheet("font-size: 17px; font-weight: 700; color: #1f2937; margin-bottom: 15px; padding: 4px; font-family: 'Segoe UI', sans-serif;")

        # Stats
        stats_frame = QFrame()
        stats_frame.setStyleSheet(card_style)
        stats_frame.setMinimumSize(150, 100)
        
        stats_layout = QFormLayout(stats_frame)
        stats_layout.setLabelAlignment(Qt.AlignRight)
        stats_layout.setFormAlignment(Qt.AlignHCenter)
        stats_layout.setSpacing(8)
        self.therapy_usage_label = QLabel("(0.0) hours")
        self.machine_up_time_label = QLabel("(0.0) hours")
        stats_layout.addRow("Therapy Usage:", self.therapy_usage_label)
        stats_layout.addRow("Machine Up Time:", self.machine_up_time_label)
        stats_title = QLabel("Usage Stats")
        stats_title.setStyleSheet("font-size: 12px; font-weight: 700; color: #1f2937; margin-bottom: 12px; padding: 4px; font-family: 'Segoe UI', sans-serif;")

        # Alerts
        alerts_frame = QFrame()
        alerts_frame.setStyleSheet(card_style)
        alerts_frame.setMinimumSize(150, 140)
        alerts_layout = QVBoxLayout(alerts_frame)
        alerts_layout.setSpacing(5)
        self.alert_labels = {}
        for setting in ["IMODE", "Leak Alert", "Sleep Mode", "Mask Type", "Ramp Time", "Humidifier"]:
            label = QLabel(f"{setting}: (OFF)")
            alerts_layout.addWidget(label)
            self.alert_labels[setting] = label
        alerts_title = QLabel("Alerts & Settings")
        alerts_title.setStyleSheet("font-size: 18px; font-weight: 700; color: #1f2937; margin-bottom: 4px; padding: 4px; font-family: 'Segoe UI', sans-serif;")
        # Report
        report_frame = QFrame()
        report_frame.setStyleSheet(card_style)
        report_frame.setMinimumSize(150, 100)
        report_layout = QVBoxLayout(report_frame)
        report_layout.setSpacing(8)
        calendar = QCalendarWidget()
        calendar.setGridVisible(True)
        calendar.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        calendar.setStyleSheet("""
            QCalendarWidget {
                background-color: white;
                color: black;
                font-family: 'Segoe UI', sans-serif;
            }
            QCalendarWidget QWidget#qt_calendar_navigationbar {
                background-color: white;
                border: none;
                min-height: 30px;
            }
            QCalendarWidget QToolButton {
                color: black;
                font-size: 17px;
                font-weight: bold;
                border: none;
                background: none;
                padding: 5px;
            }
            QCalendarWidget QToolButton:hover {
                background-color: #f0f0f0;
            }
            QCalendarWidget QToolButton:pressed {
                background-color: #e0e0e0;
            }
            QCalendarWidget QWidget#qt_calendar_navigation_layout {
                background-color: white;
            }
            QCalendarWidget QWidget#qt_calendar_weeknumber {
                background-color: white;
                color: black;
                font-weight: bold;
            }
            QCalendarWidget QWidget#qt_calendar_monthcontainer {
                background-color: white;
            }
            QCalendarWidget QAbstractItemView {
                background-color: white;
                color: black;
                selection-background-color: #0078d7;
                selection-color: white;
                alternate-background-color: #fbfbfb;
            }
            QCalendarWidget QAbstractItemView::item                
                padding: 5px;
                border: none;
            }
            QCalendarWidget QAbstractItemView::item:selected {
                background-color: #0078d7;
                color: white;
            }
        """)
        # Device Status
        status_layout = QHBoxLayout()
        status_layout.setSpacing(10)
        status_layout.setAlignment(Qt.AlignLeft)
        self.status_label = QLabel("●")
        self.status_label.setStyleSheet("QLabel { font-size: 26px; color: #e74c3c; font-family: 'Segoe UI', sans-serif; }")
        self.status_text = QLabel("Not Connected")
        self.status_text.setStyleSheet("QLabel { font-size: 14px; color: #e74c3c; font-weight: 500; font-family: 'Segoe UI', sans-serif; padding-left: 8px; }")
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.status_text) 
        status_layout.addStretch()

        status_frame = QFrame()
        status_frame.setLayout(status_layout)
        status_frame.setStyleSheet("QFrame { background: transparent; padding: 10px 0; }")

        pdf_btn = QPushButton("Export PDF")
        pdf_btn.clicked.connect(self.export_pdf)
        csv_btn = QPushButton("Export CSV") 
        csv_btn.clicked.connect(self.export_csv)    
        btn_layout = QHBoxLayout()   
        btn_layout.setSpacing(10)
        btn_layout.addWidget(pdf_btn)
        btn_layout.addWidget(csv_btn)

        report_layout.addWidget(calendar)
        report_layout.addWidget(status_frame)
        report_layout.addLayout(btn_layout)

        report_title = QLabel("Report")
        report_title.setStyleSheet("font-size: 18px; font-weight: 700; color: #1f2937; margin-bottom: 12px; padding: 4px; font-family: 'Segoe UI', sans-serif;")

        pdf_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #27ae60, stop:1 #2ecc71);
                color: white;
                border-radius: 8px;
                padding: 12px 24px;
                font-weight: 600;
                font-size: 14px;
                font-family: 'Segoe UI', sans-serif;
                border: none;
                min-width: 120px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2ecc71, stop:1 #27ae60);
                box-shadow: 0 4px 12px rgba(46, 204, 113, 0.3);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #229954, stop:1 #1e8449);
            }
        """)
        
        csv_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f39c12, stop:1 #e67e22);
                color: white;
                border-radius: 8px;
                padding: 12px 24px;
                font-weight: 600;
                font-size: 14px;
                font-family: 'Segoe UI', sans-serif;
                border: none;
                min-width: 120px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #e67e22, stop:1 #f39c12);
                box-shadow: 0 4px 12px rgba(243, 156, 18, 0.3);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #d35400, stop:1 #e67e22);
            }
        """)
        # Grid layout - NOW INCLUDING REPORT
        grid = QGridLayout()
        grid.setSpacing(15)
        grid.setContentsMargins(0, 0, 0, 0)
        # Row 0: Titles
        grid.addWidget(patient_title, 0, 0)
        grid.addWidget(stats_title, 0, 1)
        grid.addWidget(alerts_title, 0, 2)
        grid.addWidget(report_title, 0, 3)        # ← Add Report Title
        # Row 1–2: Main cards
        grid.addWidget(patient_frame, 1, 0, 2, 1)
        grid.addWidget(stats_frame, 1, 1, 2, 1)
        grid.addWidget(alerts_frame, 1, 2, 2, 1)
        grid.addWidget(report_frame, 1, 3, 2, 1)  # ← NOW VISIBLE!
        # Optional: Adjust column stretch so report doesn't squeeze others
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 2)
        grid.setColumnStretch(2, 2)
        grid.setColumnStretch(3, 3)  # Give report more space

        grid.setRowStretch(1, 1)
        grid.setRowStretch(2, 1)

        main_layout.addLayout(grid)

        scroll = QScrollArea()
        scroll.setWidget(page)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea { 
                border: none; 
                background: transparent; 
            } 
            QScrollBar:vertical { 
                background: rgba(0,0,0,0.1); 
                border-radius: 8px; 
                width: 10px; 
            } 
            QScrollBar::handle:vertical { 
                background: #1f6feb; 
                border-radius: 5px; 
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover { 
                background: #ff6a00; 
            }
        """)
        return scroll

    def on_type_change(self, text):
        self.machine_type = text
        self.update_button_states()

    def fetch_settings(self):
        serial = self.serial_input.text().strip()
        if not serial:
            QMessageBox.warning(self, "Error", "Please enter a serial number.")
            return

        machine_type_selected = self.machine_type_combo.currentText()

        url = f"https://backend-production-9c17.up.railway.app/api/devices/{serial}/data?limit=1"
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            api_data = response.json()
            if not api_data.get("success") or not api_data["data"].get("records"):
                QMessageBox.warning(self, "Error", "No data found for this device.")
                return

            latest_record = api_data["data"]["records"][0]
            device_type_api = latest_record.get("device_type", "BIPAP")

            if device_type_api != machine_type_selected:
                reply = QMessageBox.question(self, "Type Mismatch", f"API reports {device_type_api}, selected {machine_type_selected}. Proceed?")
                if reply != QMessageBox.Yes:
                    return

            self.machine_type = device_type_api
            self.machine_type_combo.setCurrentText(device_type_api)
            self.update_button_states()

            sections = latest_record["parsed_data"]["sections"]

            # Build CSV line from sections
            sections_list = []
            for key in sections:
                sections_list.append(key)
                sections_list.extend([str(v) for v in sections[key]])

            csv_line = "*" + ",".join(sections_list) + "#"

            message = {"device_data": csv_line}

            self.update_all_from_cloud(message)

            self.machine_serial = serial
            self.serial_input.setText(serial)
            self.info_label.setText(f"User: ({self.user_name})    |    Machine S/N: ({serial})")

            QMessageBox.information(self, "Success", "Settings fetched from API and loaded into UI!")
            

        except requests.exceptions.RequestException as e:
            QMessageBox.warning(self, "Error", f"API request failed: {str(e)}")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to process API data: {str(e)}")

# Run
if __name__ == "__main__":
    print(f"Current working directory: {os.getcwd()}")
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    app = QApplication(sys.argv)
    window = LoginWindow()
    window.show()
    sys.exit(app.exec_())