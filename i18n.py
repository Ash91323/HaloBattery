"""Small built-in UI catalogue; English source strings are the fallback."""
import ctypes
import locale
import re
import sys

LANGUAGES = ("auto", "en", "zh-TW")
_language = "en"

ZH_TW = {
    "Connecting to update server...": "正在連線至更新伺服器…",
    "Download complete; preparing installation...": "下載完成，正在準備安裝…",
    "Downloading {percent}% ({done:.1f} / {total:.1f} MB)": "正在下載 {percent}%（{done:.1f} / {total:.1f} MB）",
    'Version {version} is available. Right-click a battery icon and choose "Install v{version} and restart…".':
        '已有新版本 {version}。請在電量圖示上按右鍵，選擇「安裝 v{version} 並重新啟動…」。',
    "Install v{version} and restart…": "安裝 v{version} 並重新啟動…",
    "Downloading and preparing update…": "正在下載並準備更新…",
    "Update failed": "更新失敗",
    "Could not install the update. The current version is unchanged.\n{error}": "無法安裝更新，目前版本未變更。\n{error}",
    "Installation failed. The previous version was kept or restored.\n{error}": "安裝失敗，已保留或還原原版本。\n{error}",
    "Language": "語言",
    "Follow system": "跟隨系統",
    "Preferences": "偏好設定",
    "Refresh now": "立即更新",
    "Hidden devices": "已隱藏的裝置",
    "Diagnostics…": "診斷資訊…",
    "Exit (v{version})": "結束（v{version}）",
    "No devices found": "找不到裝置",
    "no devices found": "找不到裝置",
    "No devices shown ({count} hidden)": "未顯示裝置（已隱藏 {count} 個）",
    "Show {name}": "顯示 {name}",
    "Rename…": "重新命名…",
    "Reset name": "還原名稱",
    "Icon": "圖示",
    "Low battery alert at": "低電量提醒門檻",
    "Hide this device": "隱藏此裝置",
    "Default ({level}%)": "預設（{level}%）",
    "Default (off)": "預設（關閉）",
    "Poll interval": "電量檢查間隔",
    "Low battery alert": "低電量提醒",
    "Alert when fully charged": "充飽電時提醒",
    "Estimated time left": "預估剩餘使用時間",
    "Quiet while gaming": "遊戲時暫停提醒",
    "Windows Bluetooth devices": "Windows 藍牙裝置",
    "PlayStation full mode (Bluetooth)": "PlayStation 完整模式（藍牙）",
    "Device types": "裝置類型",
    "Device pictogram": "裝置類型圖示",
    "Percentage in the icon": "在圖示中顯示百分比",
    "Charging animation": "充電動畫",
    "Icon colour": "圖示顏色",
    "Status file for other apps": "供其他應用程式使用的狀態檔",
    "Start with Windows": "隨 Windows 啟動",
    "Check for updates": "檢查更新",
    "Download v{version}…": "下載 v{version}…",
    "Download update…": "下載更新…",
    "Automatic": "自動",
    "White": "白色",
    "Black": "黑色",
    "Off": "關閉",
    "15 s": "15 秒",
    "30 s": "30 秒",
    "1 min": "1 分鐘",
    "2 min": "2 分鐘",
    "5 min": "5 分鐘",
    "Mouse": "滑鼠",
    "Keyboard": "鍵盤",
    "Headset": "耳機",
    "Controller": "控制器",
    "Bluetooth": "藍牙",
    "8BitDo controllers": "8BitDo 控制器",
    "ASUS ROG / TUF mice": "ASUS ROG / TUF 滑鼠",
    "AULA / Compx keyboards": "AULA / Compx 鍵盤",
    "Corsair headsets": "Corsair 耳機",
    "G-Wolves mice": "G-Wolves 滑鼠",
    "LAMZU mice": "LAMZU 滑鼠",
    "Lofree keyboards": "Lofree 鍵盤",
    "MCHOSE mice": "MCHOSE 滑鼠",
    "Nintendo Switch controllers": "Nintendo Switch 控制器",
    "PlayStation controllers": "PlayStation 控制器",
    "Pulsar / ATK VXE mice": "Pulsar / ATK VXE 滑鼠",
    "Razer mice and headsets": "Razer 滑鼠與耳機",
    "Xbox-compatible controllers": "Xbox 相容控制器",
    "no link (off or asleep)": "未連線（已關機或休眠）",
    ", charging": "，充電中",
    " (last known value, device asleep)": "（上次讀取的電量，裝置休眠中）",
    ", {left}": "，{left}",
    "Low battery": "電量不足",
    "Fully charged": "已充飽電",
    "battery is low": "電量不足",
    "{level}% left": "剩餘 {level}% 電量",
    "{name}: {left}. Time to charge.": "{name}：{left}，請充電。",
    "{name} is fully charged.": "{name} 已充飽電。",
    'Version {version} is available. Right-click a battery icon and choose "Download v{version}…".':
        '已有新版本 {version}。請在電量圖示上按右鍵，選擇「下載 v{version}…」。',
    "Halo Battery update": "Halo Battery 更新",
    "New name for this device:": "請輸入此裝置的新名稱：",
    "Halo Battery - Rename": "Halo Battery - 重新命名",
    "less than 1 h of use left": "剩餘使用時間不到 1 小時",
    "about {hours} h of use left": "約可再使用 {hours} 小時",
    "about {days} days of use left": "約可再使用 {days} 天",
    "connected, battery level not reported yet": "已連線，尚未回報電量",
    "connected, battery level not reported": "已連線，未回報電量",
    "connected, battery not readable (another app may hold it)": "已連線，無法讀取電量（可能被其他程式佔用）",
    "about {level}%": "約 {level}%",
    "about {level}% ({state})": "約 {level}%（{state}）",
    "empty": "電量耗盡", "low": "低", "medium": "中", "full": "滿",
    "good": "充足", "critical": "極低",
    "Halo Battery is running from a temporary folder (straight from the ZIP). Extract the ZIP to a folder of its own, run HaloBattery.exe from there, then turn on Start with Windows.":
        "Halo Battery 正從暫存資料夾執行（直接從 ZIP 開啟）。請先將 ZIP 解壓縮到獨立資料夾，執行其中的 HaloBattery.exe，再開啟「隨 Windows 啟動」。",
}


def system_language():
    """Prefer Windows display language, rather than its regional date format."""
    if sys.platform == "win32":
        try:
            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            return locale.windows_locale.get(lang_id, "en")
        except (AttributeError, OSError):
            pass
    try:
        return locale.getlocale()[0] or "en"
    except (ValueError, TypeError):
        return "en"


def resolve_language(language):
    value = system_language() if language == "auto" else language
    parts = str(value).replace("_", "-").lower().split("-")
    if parts[0] == "zh" and ("hant" in parts or any(p in parts for p in ("tw", "hk", "mo"))):
        return "zh-TW"
    return "en"


def set_language(language):
    global _language
    _language = resolve_language(language)


def get_language():
    return _language


def tr(message, **values):
    text = ZH_TW.get(message, message) if _language == "zh-TW" else message
    return text.format(**values) if values else text


def status_text(text):
    """Translate provider descriptions only at the UI boundary."""
    match = re.fullmatch(r"about (\d+)%\s*(?:\((empty|low|medium|full|good|critical)\))?", text)
    if match:
        level, state = match.groups()
        return (tr("about {level}% ({state})", level=level, state=tr(state)) if state
                else tr("about {level}%", level=level))
    return tr(text)
