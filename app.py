import streamlit as st
import requests
import datetime
import sqlite3
import hashlib
import os
import time
import random

# --- CONFIGURATION ---
FICHIER_LIENS = "mes_liens_ade.txt"
DB_FILE = "radar_upec.db"
CACHE_TIMEOUT = 1800 
MAX_QUOTA_HEBDO = 3
MAX_DUREE_HEURES = 2
MIN_GROUPE = 5
MIN_CONFIRMATION_REQUISE = 4
CHECKIN_TIME_MIN = 15

st.set_page_config(page_title="Radar UPEC", page_icon="🏢", layout="wide")

# --- INITIALISATION DB ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (email TEXT PRIMARY KEY, password TEXT, nom TEXT, ade_url TEXT DEFAULT "")''')
    c.execute('''CREATE TABLE IF NOT EXISTS reservations (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        user_email TEXT, 
        salle TEXT, 
        date_str TEXT, 
        start_time TEXT, 
        end_time TEXT, 
        participants TEXT DEFAULT "", 
        confirmed_list TEXT DEFAULT ""
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS admin_locks (salle TEXT PRIMARY KEY, reason TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS restrictions (salle TEXT, date_str TEXT, hour INTEGER, type TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS room_equipment (salle TEXT, icon TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS cache_ade (salle TEXT, debut TEXT, fin TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT)''')
    c.execute("INSERT OR IGNORE INTO metadata (key, value) VALUES ('force_groupe', '0')")
    conn.commit()
    conn.close()

init_db()

# --- INITIALISATION SESSION ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.username = ""
    st.session_state.email = ""
    st.session_state.is_admin = False
    st.session_state.ade_url = ""
if 'page' not in st.session_state: st.session_state.page = "login"
if 'etage_choisi' not in st.session_state: st.session_state.etage_choisi = None
if 'expanded_grp' not in st.session_state: st.session_state.expanded_grp = None

# --- CSS (V44 - MOBILE & DARK MODE FIX) ---
def inject_custom_css(page_type="standard"):
    base_css = """
<style>
    /* 1. FORCE LE TEXTE NOIR PARTOUT SUR FOND BLANC */
    html, body, [class*="css"] {
        font-family: sans-serif;
    }
    
    /* Boutons : Fond Blanc, Texte Noir, Bordure Grise */
    div.stButton > button {
        background-color: #ffffff !important;
        color: #000000 !important;
        border: 1px solid #cccccc !important;
    }
    div.stButton > button p {
        color: #000000 !important;
    }
    div.stButton > button:hover {
        border-color: #ff2b4a !important;
        color: #ff2b4a !important;
    }
    div.stButton > button:hover p {
        color: #ff2b4a !important;
    }

    /* Exceptions Boutons Spéciaux (Validations, etc.) */
    button[kind="primary"] {
        background-color: #ff2b4a !important;
        color: #ffffff !important;
        border: none !important;
    }
    button[kind="primary"] p {
        color: #ffffff !important;
    }

    /* 2. CLASSES SPÉCIFIQUES */
    .red-card {
        background-color: #ff2b4a;
        color: white !important;
        border-radius: 15px;
        padding: 30px 0; /* Réduit pour mobile */
        text-align: center;
        font-weight: 800;
        font-size: 50px; /* Réduit pour mobile */
        margin-bottom: 10px;
    }
    
    /* Accordéons (Gris clair) */
    .streamlit-expanderHeader {
        background-color: #f0f2f6 !important;
        color: #000000 !important;
    }
    .streamlit-expanderHeader p {
        color: #000000 !important;
    }
    .streamlit-expanderContent {
        background-color: #ffffff !important;
        color: #000000 !important;
        border: 1px solid #f0f2f6;
    }

    /* Cartes (Ticket, Recap, Planning) */
    .recap-box, .ticket-card, .cours-card {
        background-color: #ffffff !important;
        color: #000000 !important;
        border: 1px solid #ddd;
        border-radius: 8px;
        padding: 15px;
        margin-bottom: 10px;
    }
    /* Force tout le texte interne en noir */
    .recap-box *, .ticket-card *, .cours-card * {
        color: #000000 !important;
    }
    
    /* Indicateurs couleur */
    .confirmed-resa { border-left: 5px solid #28a745; padding-left: 10px; }
    .pending-resa { border-left: 5px solid #ffc107; padding-left: 10px; }
    .cours-card { border-left: 5px solid #ff2b4a; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }

    /* 3. OPTIMISATION MOBILE */
    .block-container {
        padding-top: 2rem !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
        padding-bottom: 3rem !important;
    }
</style>
"""
    
    # CSS SPÉCIFIQUE GROS BOUTONS (ACCUEIL)
    if page_type == "accueil":
        custom_css = """
<style>
    div.stButton > button {
        width: 100%;
        height: auto !important; /* Laisse la hauteur s'adapter sur mobile */
        min-height: 100px;
        font-size: 24px !important; /* Un peu plus petit pour tenir sur mobile */
        font-weight: 800 !important;
        border-radius: 15px !important;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    /* Exceptions petits boutons */
    div[data-testid="stHorizontalBlock"] button, 
    div[data-testid="stVerticalBlock"] button,
    div.stButton button[kind="primary"] { 
        min-height: 0px !important;
        height: auto !important;
        font-size: 16px !important; 
        box-shadow: none;
    }
</style>
"""
    else:
        # CSS STANDARD (DETAIL)
        custom_css = """
<style>
    div.stButton > button {
        height: auto !important;
        min-height: 50px;
        font-size: 16px !important;
        font-weight: bold;
    }
</style>
"""
    st.markdown(base_css + custom_css, unsafe_allow_html=True)

# --- BACKEND UTILS ---

JOURS_FR = {0: "Lundi", 1: "Mardi", 2: "Mercredi", 3: "Jeudi", 4: "Vendredi", 5: "Samedi", 6: "Dimanche"}
MOIS_FR = {1: "Janvier", 2: "Février", 3: "Mars", 4: "Avril", 5: "Mai", 6: "Juin", 7: "Juillet", 8: "Août", 9: "Septembre", 10: "Octobre", 11: "Novembre", 12: "Décembre"}

def format_date_joli(date_obj):
    return f"{JOURS_FR[date_obj.weekday()]} {date_obj.day} {MOIS_FR[date_obj.month]}"

def hash_password(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def verifier_connexion(email, password):
    if email == "admin" and password == "admin": return ("Administrateur", "")
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT nom, ade_url FROM users WHERE email=? AND password=?", (email, hash_password(password)))
    result = c.fetchone()
    conn.close()
    return result if result else (None, None)

def creer_compte(email, password, nom):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (email, password, nom, ade_url) VALUES (?, ?, ?, '')", (email, hash_password(password), nom))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def save_ade_url(email, url):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET ade_url=? WHERE email=?", (url, email))
    conn.commit()
    conn.close()

# --- PARSING ---
def fetch_and_parse_ical(url):
    events = []
    try:
        r = requests.get(url.strip(), timeout=5)
        if r.status_code == 200:
            cours_liste = r.text.split("BEGIN:VEVENT")
            for cours in cours_liste:
                if "END:VEVENT" not in cours: continue
                debut, fin, lieu, summary = None, None, "", ""
                for ligne in cours.split('\n'):
                    l = ligne.strip()
                    if l.startswith("DTSTART:"):
                        try: debut = datetime.datetime.strptime(l.replace("DTSTART:","").replace("Z","").strip(), '%Y%m%dT%H%M%S')
                        except: pass
                    elif l.startswith("DTEND:"):
                        try: fin = datetime.datetime.strptime(l.replace("DTEND:","").replace("Z","").strip(), '%Y%m%dT%H%M%S')
                        except: pass
                    elif l.startswith("LOCATION:"):
                        lieu = l.replace("LOCATION:", "").replace("\\", "")
                    elif l.startswith("SUMMARY:"):
                        summary = l.replace("SUMMARY:", "").replace("\\", "")
                if debut and fin:
                    events.append({"titre": summary, "lieu": lieu, "debut": debut, "fin": fin})
    except: pass
    return events

def get_mon_planning(raw_urls):
    if not raw_urls: return []
    all_events = []
    urls = [u.strip() for u in raw_urls.split('\n') if u.strip().startswith("http")]
    for url in urls:
        events = fetch_and_parse_ical(url)
        all_events.extend(events)
    all_events.sort(key=lambda x: x['debut'])
    return all_events

# --- METIERS ---
def toggle_equipment(salle, icon):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT icon FROM room_equipment WHERE salle=? AND icon=?", (salle, icon))
    if c.fetchone(): c.execute("DELETE FROM room_equipment WHERE salle=? AND icon=?", (salle, icon))
    else: c.execute("INSERT INTO room_equipment VALUES (?, ?)", (salle, icon))
    conn.commit()
    conn.close()

def get_room_icons(salle):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT icon FROM room_equipment WHERE salle=?", (salle,))
    rows = c.fetchall()
    conn.close()
    return " " + " ".join([r[0] for r in rows]) if rows else ""

def has_equipment(salle, icon):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT icon FROM room_equipment WHERE salle=? AND icon=?", (salle, icon))
    res = c.fetchone()
    conn.close()
    return res is not None

def get_admin_config_groupe():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT value FROM metadata WHERE key='force_groupe'")
    res = c.fetchone()
    conn.close()
    return res[0] == "1" if res else False

def set_admin_config_groupe(actif: bool):
    val = "1" if actif else "0"
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("REPLACE INTO metadata (key, value) VALUES ('force_groupe', ?)", (val,))
    conn.commit()
    conn.close()

def clean_no_show_reservations():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    today_s = datetime.date.today().strftime("%Y-%m-%d")
    now = datetime.datetime.now()
    limit_time = (now - datetime.timedelta(minutes=CHECKIN_TIME_MIN)).strftime("%H:%M")
    c.execute("SELECT id, user_email, participants, confirmed_list FROM reservations WHERE date_str=? AND start_time < ?", (today_s, limit_time))
    rows = c.fetchall()
    for r in rows:
        res_id, creator, parts_str, conf_str = r
        all_humans = [creator] + (parts_str.split(',') if parts_str else [])
        confirmed_humans = conf_str.split(',') if conf_str else []
        confirmed_humans = [x for x in confirmed_humans if x]
        nb_confirmed = len(confirmed_humans)
        if len(all_humans) > 1:
            if nb_confirmed < MIN_CONFIRMATION_REQUISE:
                c.execute("DELETE FROM reservations WHERE id=?", (res_id,))
        else:
            if nb_confirmed == 0:
                c.execute("DELETE FROM reservations WHERE id=?", (res_id,))
    conn.commit()
    conn.close()

def confirm_reservation_user(res_id, user_email):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT confirmed_list FROM reservations WHERE id=?", (res_id,))
    row = c.fetchone()
    if row:
        current_list = row[0].split(',') if row[0] else []
        if user_email not in current_list:
            current_list.append(user_email)
            new_str = ",".join(current_list)
            c.execute("UPDATE reservations SET confirmed_list=? WHERE id=?", (new_str, res_id))
    conn.commit()
    conn.close()

def verifier_quota_hebdo(email, date_obj):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    start_week = date_obj - datetime.timedelta(days=date_obj.weekday())
    end_week = start_week + datetime.timedelta(days=6)
    c.execute("SELECT user_email, participants FROM reservations WHERE date_str >= ? AND date_str <= ?", 
              (start_week.strftime("%Y-%m-%d"), end_week.strftime("%Y-%m-%d")))
    rows = c.fetchall()
    count = 0
    for r in rows:
        if r[0] == email or (r[1] and email in r[1]): count += 1
    conn.close()
    return count < MAX_QUOTA_HEBDO, count

def get_restriction(salle, date_obj, hour):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    date_s = date_obj.strftime("%Y-%m-%d")
    c.execute("SELECT type FROM restrictions WHERE salle=? AND date_str=? AND hour=-1", (salle, date_s))
    res_day = c.fetchone()
    if res_day: 
        conn.close()
        return res_day[0]
    c.execute("SELECT type FROM restrictions WHERE salle=? AND date_str=? AND hour=?", (salle, date_s, hour))
    res_hour = c.fetchone()
    conn.close()
    return res_hour[0] if res_hour else None

def set_restriction(salle, date_obj, hour, type_rest):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    date_s = date_obj.strftime("%Y-%m-%d")
    if type_rest == "DAY_BLOCK":
        c.execute("DELETE FROM restrictions WHERE salle=? AND date_str=?", (salle, date_s))
        c.execute("INSERT INTO restrictions VALUES (?, ?, ?, ?)", (salle, date_s, -1, "DAY_BLOCK"))
        c.execute("DELETE FROM reservations WHERE salle=? AND date_str=?", (salle, date_s))
    elif type_rest == "NONE":
        c.execute("DELETE FROM restrictions WHERE salle=? AND date_str=? AND (hour=? OR hour=-1)", (salle, date_s, hour))
    else:
        c.execute("DELETE FROM restrictions WHERE salle=? AND date_str=? AND hour=?", (salle, date_s, hour))
        c.execute("INSERT INTO restrictions VALUES (?, ?, ?, ?)", (salle, date_s, hour, type_rest))
        if type_rest == "BLOCK":
            h_str = f"{hour:02d}:00"
            c.execute("DELETE FROM reservations WHERE salle=? AND date_str=? AND start_time=?", (salle, date_s, h_str))
    conn.commit()
    conn.close()

def admin_mass_lock_etage(date_obj, hour, salles_list, type_rest="BLOCK"):
    for s in salles_list: set_restriction(s, date_obj, hour, type_rest)

def get_stats_admin():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    today = datetime.date.today().strftime("%Y-%m-%d")
    c.execute("SELECT COUNT(*) FROM reservations WHERE date_str=?", (today,))
    total = c.fetchone()[0]
    c.execute("SELECT salle FROM reservations WHERE date_str=?", (today,))
    rows = c.fetchall()
    etages = {"P1": 0, "P2": 0, "P3": 0, "P4": 0}
    for r in rows:
        if "P1" in r[0]: etages["P1"] += 1
        elif "P2" in r[0]: etages["P2"] += 1
        elif "P3" in r[0]: etages["P3"] += 1
        elif "P4" in r[0]: etages["P4"] += 1
    c.execute("SELECT start_time FROM reservations WHERE date_str=?", (today,))
    time_rows = c.fetchall()
    heures = {f"{h}h": 0 for h in range(8, 21)}
    for tr in time_rows:
        try:
            h_int = int(tr[0].split(':')[0])
            key = f"{h_int}h"
            if key in heures: heures[key] += 1
        except: pass
    conn.close()
    return total, etages, heures

def manage_group_action(email, salle, date_obj, heure_debut, action_type):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    date_s = date_obj.strftime("%Y-%m-%d")
    h_str = heure_debut.strftime("%H:%M")
    
    c.execute("SELECT id, user_email, participants FROM reservations WHERE salle=? AND date_str=? AND start_time <= ? AND end_time > ?", 
              (salle, date_s, h_str, h_str))
    existing = c.fetchone()
    
    status, msg = "ok", ""
    
    if existing:
        res_id, creator, parts_str = existing
        participants = parts_str.split(",") if parts_str else []
        
        if action_type == "leave":
            if creator == email:
                if participants:
                    new_boss = participants.pop(0)
                    new_parts_str = ",".join(participants)
                    c.execute("UPDATE reservations SET user_email=?, participants=? WHERE id=?", (new_boss, new_parts_str, res_id))
                    msg = f"Vous avez quitté. {new_boss} est responsable."
                else:
                    c.execute("DELETE FROM reservations WHERE id=?", (res_id,))
                    msg = "Réservation annulée (Groupe vide)."
            elif email in participants:
                participants.remove(email)
                c.execute("UPDATE reservations SET participants=? WHERE id=?", (",".join(participants), res_id))
                msg = "Vous avez quitté le groupe."
        
        elif action_type == "cancel":
             c.execute("DELETE FROM reservations WHERE id=?", (res_id,))
             msg = "Réservation annulée."

        elif action_type == "join":
            ok_q, _ = verifier_quota_hebdo(email, date_obj)
            if not ok_q:
                status, msg = "error", "Quota hebdo dépassé !"
            else:
                if email not in participants and email != creator:
                    participants.append(email)
                    c.execute("UPDATE reservations SET participants=? WHERE id=?", (",".join(participants), res_id))
                    msg = f"Groupe rejoint ({1+len(participants)}/{MIN_GROUPE})."
                else:
                    msg = "Vous êtes déjà dans le groupe."
    else:
        status, msg = "error", "Réservation introuvable."
                
    conn.commit()
    conn.close()
    return status, msg

def manage_clic_salle(email, salle, date_obj, heure_debut, heure_fin, is_forced_groupe):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    date_s = date_obj.strftime("%Y-%m-%d")
    h_str = heure_debut.strftime("%H:%M")
    
    rest = get_restriction(salle, date_obj, heure_debut.hour)
    if rest == "BLOCK" or rest == "DAY_BLOCK":
        conn.close()
        return "error", "⛔ Salle bloquée par l'admin."
    
    c.execute("INSERT INTO reservations (user_email, salle, date_str, start_time, end_time, participants, confirmed_list) VALUES (?, ?, ?, ?, ?, ?, '')",
              (email, salle, date_s, h_str, heure_fin.strftime("%H:%M"), ""))
    
    msg = "Groupe initié (1/5) !" if is_forced_groupe else "Salle réservée (Solo)."
    conn.commit()
    conn.close()
    return "ok", msg

def get_db_reservations(date_obj):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT salle, start_time, end_time, user_email, participants FROM reservations WHERE date_str=?", (date_obj.strftime("%Y-%m-%d"),))
    rows = c.fetchall()
    conn.close()
    return rows

def get_mes_reservations_futures(email):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    today = datetime.date.today().strftime("%Y-%m-%d")
    c.execute("SELECT salle, date_str, start_time, end_time, confirmed_list, id, participants, user_email FROM reservations WHERE (user_email=? OR participants LIKE ?) AND date_str >= ? ORDER BY date_str ASC", (email, f"%{email}%", today))
    rows = c.fetchall()
    conn.close()
    return rows

def charger_liens():
    if not os.path.exists(FICHIER_LIENS): return []
    with open(FICHIER_LIENS, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip().startswith("http")]

def nettoyer_nom_salle(nom_brut):
    if "(" in nom_brut: return nom_brut.split("(")[0].strip()
    return nom_brut

def update_cache_ade_si_necessaire():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT value FROM metadata WHERE key='last_update'")
    res = c.fetchone()
    now_ts = time.time()
    clean_no_show_reservations()
    if not res or (now_ts - float(res[0]) > CACHE_TIMEOUT):
        c.execute("DELETE FROM cache_ade")
        liens = charger_liens()
        for url in liens:
            try:
                r = requests.get(url, timeout=5)
                if r.status_code == 200:
                    cours_liste = r.text.split("BEGIN:VEVENT")
                    for cours in cours_liste:
                        if "END:VEVENT" not in cours: continue
                        debut, fin, lieu = None, None, ""
                        for ligne in cours.split('\n'):
                            l = ligne.strip()
                            if l.startswith("DTSTART:"):
                                try: debut = datetime.datetime.strptime(l.replace("DTSTART:","").replace("Z","").strip(), '%Y%m%dT%H%M%S')
                                except: pass
                            elif l.startswith("DTEND:"):
                                try: fin = datetime.datetime.strptime(l.replace("DTEND:","").replace("Z","").strip(), '%Y%m%dT%H%M%S')
                                except: pass
                            elif l.startswith("LOCATION:"):
                                lieu = l.replace("LOCATION:", "").replace("\\", "")
                        if lieu and debut and fin:
                            parts = lieu.split(',')
                            for s in parts:
                                s = s.strip()
                                if "CC P" in s:
                                    c.execute("INSERT INTO cache_ade VALUES (?, ?, ?)", (nettoyer_nom_salle(s), debut.isoformat(), fin.isoformat()))
            except: pass
        c.execute("REPLACE INTO metadata VALUES ('last_update', ?)", (str(now_ts),))
        conn.commit()
    conn.close()

def get_planning_sql(date_choisie):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    d_start = datetime.datetime.combine(date_choisie, datetime.time(0,0))
    d_end = datetime.datetime.combine(date_choisie, datetime.time(23,59))
    c.execute("SELECT salle, debut, fin FROM cache_ade WHERE debut >= ? AND debut <= ?", (d_start.isoformat(), d_end.isoformat()))
    rows = c.fetchall()
    conn.close()
    planning = []
    for r in rows:
        try: d = datetime.datetime.fromisoformat(r[1])
        except: d = datetime.datetime.now()
        try: f = datetime.datetime.fromisoformat(r[2])
        except: f = datetime.datetime.now()
        planning.append({"salle": r[0], "debut": d, "fin": f})
    return planning

def analyse_salle_intelligente(salle, planning_jour, resas_db, time_choisi, my_email, date_obj):
    restriction = get_restriction(salle, date_obj, time_choisi.hour)
    if restriction == "DAY_BLOCK": return "admin_lock", datetime.time(20,0), "⛔ Fermée (Journée)", False
    if restriction == "BLOCK": return "admin_lock", datetime.time(20,0), "⛔ Fermée (Créneau)", False
    cours_now = [c for c in planning_jour if c['salle'] == salle and c['debut'].time() <= time_choisi < c['fin'].time()]
    if cours_now: return "rouge", cours_now[0]['fin'].time(), "Cours", False
    for r in resas_db:
        r_start = datetime.datetime.strptime(r[1], "%H:%M").time()
        r_end = datetime.datetime.strptime(r[2], "%H:%M").time()
        if r[0] == salle and r_start <= time_choisi < r_end:
            creator = r[3]
            parts = r[4].split(",") if r[4] else []
            nb_pers = 1 + len(parts)
            if creator == my_email:
                return "orange_moi", r_end, "Annuler", False
            elif my_email in parts:
                return "orange_moi", r_end, f"Quitter ({nb_pers}/{MIN_GROUPE})", False
            if nb_pers < MIN_GROUPE: return "bleu", r_end, f"Rejoindre ({nb_pers}/{MIN_GROUPE})", True
            return "orange", r_end, "Complet", False
    is_group_forced = (restriction == "GROUP")
    prochains = [c for c in planning_jour if c['salle'] == salle and c['debut'].time() > time_choisi]
    prochains.sort(key=lambda x: x['debut'])
    limit = prochains[0]['debut'].time() if prochains else datetime.time(20, 0)
    return "vert", limit, "Libre", is_group_forced

# --- DIALOGS ---
@st.dialog("📝 Détails de la Réservation")
def confirm_booking_dialog(email, salle, date_obj, time_start, time_end, mode_groupe):
    if 'booking_success' not in st.session_state:
        st.write("Veuillez vérifier les informations ci-dessous avant de valider.")
        st.markdown(f"""
        <div class="recap-box">
            <h4>📍 {salle}</h4>
            <p><b>Catégorie :</b> {'Groupe (5 pers min)' if mode_groupe else 'Individuel'}</p>
            <p><b>Date :</b> {format_date_joli(date_obj)}</p>
            <p><b>Horaire :</b> {time_start.strftime('%H:%M')} - {time_end.strftime('%H:%M')}</p>
            <hr>
            <p><b>Demandeur :</b> {st.session_state.username}<br>
            <small>{email}</small></p>
        </div>
        """, unsafe_allow_html=True)
        c_cancel, c_confirm = st.columns(2)
        if c_cancel.button("Annuler", use_container_width=True): st.rerun()
        if c_confirm.button("✅ Valider", type="primary", use_container_width=True):
            status, msg = manage_clic_salle(email, salle, date_obj, time_start, time_end, mode_groupe)
            if status == "error": st.error(msg)
            else:
                st.session_state.booking_success = True
                st.session_state.last_msg = msg
                st.rerun()
    else:
        st.markdown(f"""
        <div class="ticket-card" style="border-color: #28a745;">
            <h1 style="color:#28a745">✅ RÉSERVÉ !</h1>
            <p>{st.session_state.last_msg}</p>
            <hr>
            <h3>📍 {salle}</h3>
            <p>N'oubliez pas de <b>confirmer votre présence</b> (Scanner QR) en arrivant sur place !</p>
        </div>
        """, unsafe_allow_html=True)
        st.write("")
        c_new, c_deco = st.columns(2)
        if c_new.button("Nouvelle Réservation", use_container_width=True):
            del st.session_state.booking_success
            st.rerun()
        if c_deco.button("Se déconnecter", type="primary", use_container_width=True):
            st.session_state.logged_in = False
            del st.session_state.booking_success
            st.rerun()

@st.dialog("🎫 Ticket de Réservation")
def show_ticket(res_data):
    st.markdown("""
        <div class="ticket-card">
            <h2>UPEC RESERVATION</h2>
            <h1 style="color:#28a745">CONFIRMÉ</h1>
            <hr>
            <h3>📍 {}</h3>
            <p>📅 {}<br>⏰ {} - {}</p>
            <p>👤 {}</p>
            <hr>
            <img src="https://api.qrserver.com/v1/create-qr-code/?size=150x150&data=UPEC-RESA-{}" width="150">
            <br><br>
            <small>Présentez ce code à l'accueil si nécessaire.</small>
        </div>
    """.format(res_data['salle'], res_data['date'], res_data['start'], res_data['end'], st.session_state.username, res_data['id']), unsafe_allow_html=True)

# --- VUES ---
def main():
    if not st.session_state.logged_in:
        inject_custom_css("detail")
        vue_login()
    else:
        with st.sidebar:
            st.title("🎓 UPEC Companion")
            st.write(f"Bonjour **{st.session_state.username}**")
            menu = st.radio("Navigation", ["📅 Mon Planning", "🏢 Réserver une Salle", "👤 Mon Profil"])
            st.divider()
            if st.button("Se déconnecter", use_container_width=True):
                st.session_state.logged_in = False
                st.rerun()
        
        if menu == "📅 Mon Planning":
            inject_custom_css("detail")
            vue_planning()
        elif menu == "👤 Mon Profil":
            inject_custom_css("detail")
            vue_profil()
        else:
            if st.session_state.is_admin:
                if st.session_state.page == "accueil":
                    inject_custom_css("accueil")
                    vue_accueil_admin()
                elif st.session_state.page == "detail_etage":
                    inject_custom_css("detail")
                    vue_detail_etage_admin()
            else:
                if st.session_state.page == "accueil":
                    inject_custom_css("accueil")
                    vue_accueil()
                elif st.session_state.page == "detail_etage":
                    inject_custom_css("detail")
                    vue_detail_etage()

def vue_profil():
    st.title("👤 Mon Profil")
    st.write("Collez vos liens iCal (ADE) ici. Un lien par ligne.")
    current_url = st.session_state.ade_url
    new_url = st.text_area("Liens ADE (iCal)", value=current_url, height=150, placeholder="https://ade.u-pec.fr/...\nhttps://ade.u-pec.fr/...")
    if st.button("Enregistrer"):
        save_ade_url(st.session_state.email, new_url)
        st.session_state.ade_url = new_url
        st.success("Liens enregistrés !")

def vue_planning():
    st.title("📅 Mon Emploi du Temps")
    if not st.session_state.ade_url:
        st.warning("⚠️ Configurez vos liens ADE dans 'Mon Profil'.")
        return
    events = get_mon_planning(st.session_state.ade_url)
    if not events:
        st.info("Aucun cours trouvé.")
    else:
        today = datetime.date.today()
        col_today, col_tom = st.columns(2)
        with col_today:
            st.subheader("Aujourd'hui")
            events_today = [e for e in events if e['debut'].date() == today]
            if not events_today: st.caption("Rien de prévu.")
            for e in events_today:
                st.markdown(f"""
                <div class="cours-card">
                    <b>{e['debut'].strftime('%H:%M')} - {e['fin'].strftime('%H:%M')}</b><br>
                    {e['titre']}<br>
                    <small>📍 {e['lieu']}</small>
                </div>
                """, unsafe_allow_html=True)
        with col_tom:
            st.subheader("Demain")
            tom = today + datetime.timedelta(days=1)
            events_tom = [e for e in events if e['debut'].date() == tom]
            if not events_tom: st.caption("Rien de prévu.")
            for e in events_tom:
                st.markdown(f"""
                <div class="cours-card" style="border-left-color: #444;">
                    <b>{e['debut'].strftime('%H:%M')} - {e['fin'].strftime('%H:%M')}</b><br>
                    {e['titre']}<br>
                    <small>📍 {e['lieu']}</small>
                </div>
                """, unsafe_allow_html=True)

def vue_login():
    col_main, _ = st.columns([1, 1])
    with col_main:
        st.title("🎓 UPEC Companion")
        t1, t2 = st.tabs(["Connexion", "Inscription"])
        with t1:
            e = st.text_input("Email")
            p = st.text_input("Mot de passe", type="password")
            if st.button("Connexion"):
                res = verifier_connexion(e, p)
                if res[0]:
                    st.session_state.logged_in=True
                    st.session_state.username=res[0]
                    st.session_state.email=e
                    st.session_state.ade_url=res[1]
                    st.session_state.is_admin = (e == "admin")
                    st.session_state.page = "accueil"
                    st.rerun()
                else: st.error("Erreur")
        with t2:
            ne = st.text_input("Email UPEC", key="ne"); np = st.text_input("Mot de passe", key="np", type="password"); nn = st.text_input("Prénom")
            if st.button("Créer compte"):
                if creer_compte(ne, np, nn): st.success("OK !"); st.rerun()
                else: st.error("Email pris")

def vue_accueil_admin():
    st.title("🛠️ Admin Dashboard")
    tab_pilotage, tab_stats = st.tabs(["🛠️ Pilotage Salles", "📊 Statistiques"])
    with tab_pilotage:
        st.info("ℹ️ Sélectionnez un étage pour gérer les blocages.")
        current_mode = get_admin_config_groupe()
        new_mode = st.toggle("🔒 Force Groupe GLOBAL (Toutes salles)", value=current_mode)
        if new_mode != current_mode:
            set_admin_config_groupe(new_mode)
            st.rerun()
        st.write("#### Sélectionner un étage :")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("P1", use_container_width=True): st.session_state.etage_choisi="P1"; st.session_state.page="detail_etage"; st.rerun()
            if st.button("P3", use_container_width=True): st.session_state.etage_choisi="P3"; st.session_state.page="detail_etage"; st.rerun()
        with c2:
            if st.button("P2", use_container_width=True): st.session_state.etage_choisi="P2"; st.session_state.page="detail_etage"; st.rerun()
            if st.button("P4", use_container_width=True): st.session_state.etage_choisi="P4"; st.session_state.page="detail_etage"; st.rerun()
    with tab_stats:
        total, data_etages, data_heures = get_stats_admin()
        st.write("### 📈 Indicateurs du jour")
        kpi1, kpi2, kpi3 = st.columns(3)
        kpi1.metric("Réservations (Aujourd'hui)", total)
        kpi2.metric("Date", datetime.date.today().strftime("%d/%m/%Y"))
        st.write("---")
        c_chart1, c_chart2 = st.columns(2)
        with c_chart1:
            st.write("#### 🏢 Affluence par Étage")
            st.bar_chart(data_etages)
        with c_chart2:
            st.write("#### 🕒 Pic Horaire")
            st.bar_chart(data_heures)

def vue_detail_etage_admin():
    if st.button("⬅️ Retour Dashboard"): st.session_state.page="accueil"; st.rerun()
    st.write("") 
    etage = st.session_state.etage_choisi
    col_gauche, col_droite = st.columns([1, 3], gap="large")
    with col_gauche:
        st.markdown(f'<div class="red-card">{etage}</div>', unsafe_allow_html=True)
        cols_nav = st.columns(3)
        all_floors = ["P1", "P2", "P3", "P4"]
        others = [f for f in all_floors if f != etage]
        for i in range(3):
            if cols_nav[i].button(others[i], key=f"nav_{others[i]}", use_container_width=True):
                st.session_state.etage_choisi = others[i]; st.rerun()
    with col_droite:
        st.error("👮‍♂️ **GOD MODE** : Gestion des Blocages & Équipements")
        with st.container():
            c_d, c_h = st.columns([1, 2])
            today = datetime.date.today()
            if today.weekday() > 4: today += datetime.timedelta(days=(7-today.weekday()))
            jours_options, jours_map, curr = [], {}, today
            for i in range(5):
                l = format_date_joli(curr); jours_options.append(l); jours_map[l]=curr; curr+=datetime.timedelta(days=1); 
                while curr.weekday()>4: curr+=datetime.timedelta(days=1)
            choix_jour = c_d.selectbox("Date cible", options=jours_options)
            now_h = datetime.datetime.now().hour
            def_h = now_h if 8 <= now_h <= 20 else 10
            h = c_h.slider("Heure cible (Créneau d'action)", 8, 20, def_h, format="%dh", label_visibility="collapsed")
            st.write(""); st.write("") 
        date_choisie = jours_map[choix_jour]
        time_choisi = datetime.time(h, 0)
        planning_jour = get_planning_sql(date_choisie)
        resas_db = get_db_reservations(date_choisie)
        salles_etage = sorted(list(set([c['salle'] for c in planning_jour if f"CC {etage}" in c['salle']])))
        groupes = {"Niveau Parking": [], "Niveau 0": [], "Niveau 1": []}
        for s in salles_etage:
            suffixe = s.replace(f"CC {etage} ", "")
            if "P" in suffixe: groupes["Niveau Parking"].append(s)
            elif suffixe.startswith("1"): groupes["Niveau 1"].append(s)
            else: groupes["Niveau 0"].append(s)
        
        with st.expander("🎛️ Commandes Générales (Tous Niveaux)", expanded=True):
            st.write(f"Actions pour : **{etage}** le **{date_choisie}** à **{h}h**")
            c1, c2, c3 = st.columns([2, 1, 1])
            c1.write(f"🏢 **TOUT {etage}**")
            if c2.button("🔒 BLOQUER TOUT", type="primary"):
                admin_mass_lock_etage(date_choisie, h, salles_etage, "BLOCK")
                st.toast(f"Tout {etage} bloqué !"); time.sleep(0.5); st.rerun()
            if c3.button("🔓 OUVRIR TOUT"):
                admin_mass_lock_etage(date_choisie, h, salles_etage, "NONE")
                st.toast(f"Tout {etage} ouvert !"); time.sleep(0.5); st.rerun()
            st.divider()
            for nom_grp, lst in groupes.items():
                if not lst: continue
                c1, c2, c3 = st.columns([2, 1, 1])
                c1.write(f"🔹 **{nom_grp}**")
                if c2.button(f"🔒 Bloquer", key=f"lock_{nom_grp}"):
                    admin_mass_lock_etage(date_choisie, h, lst, "BLOCK")
                    st.toast(f"{nom_grp} bloqué !"); time.sleep(0.5); st.rerun()
                if c3.button(f"🔓 Ouvrir", key=f"unlock_{nom_grp}"):
                    admin_mass_lock_etage(date_choisie, h, lst, "NONE")
                    st.toast(f"{nom_grp} ouvert !"); time.sleep(0.5); st.rerun()
        st.write("---")
        st.write("#### Gestion par Salle")
        for nom_grp, lst in groupes.items():
            if not lst: continue
            is_open = (st.session_state.expanded_grp == nom_grp)
            with st.expander(f"Détail {nom_grp}", expanded=is_open):
                cols_salles = st.columns(2)
                for i, s in enumerate(lst):
                    nom_court = s.replace(f"CC {etage} ", "")
                    rest = get_restriction(s, date_choisie, h)
                    has_pc = has_equipment(s, "💻")
                    has_plug = has_equipment(s, "🔌")
                    has_pmr = has_equipment(s, "♿")
                    with cols_salles[i % 2]:
                        st.write(f"**{nom_court}**")
                        c_eq1, c_eq2, c_eq3 = st.columns(3)
                        if c_eq1.button("💻", key=f"pc_{s}", type="primary" if has_pc else "secondary", help="PC"): toggle_equipment(s, "💻"); st.rerun()
                        if c_eq2.button("🔌", key=f"pl_{s}", type="primary" if has_plug else "secondary", help="Prise"): toggle_equipment(s, "🔌"); st.rerun()
                        if c_eq3.button("♿", key=f"pm_{s}", type="primary" if has_pmr else "secondary", help="PMR"): toggle_equipment(s, "♿"); st.rerun()
                        st.caption("Contrôle d'accès :")
                        c1, c2, c3 = st.columns(3)
                        if c1.button("⛔", key=f"b_{s}", help="Bloquer 1h"): set_restriction(s, date_choisie, h, "NONE" if rest=="BLOCK" else "BLOCK"); st.rerun()
                        if c2.button("👥", key=f"g_{s}", help="Force Groupe"): set_restriction(s, date_choisie, h, "NONE" if rest=="GROUP" else "GROUP"); st.rerun()
                        if c3.button("⚫", key=f"d_{s}", help="Bloquer Jour"): set_restriction(s, date_choisie, h, "NONE" if rest=="DAY_BLOCK" else "DAY_BLOCK"); st.rerun()
                        st.write("---")

def vue_accueil():
    st.title("🏢 Radar Salles")
    update_cache_ade_si_necessaire()
    ok, nb = verifier_quota_hebdo(st.session_state.email, datetime.date.today())
    st.progress(nb/MAX_QUOTA_HEBDO, text=f"Quota Hebdo : {nb}/{MAX_QUOTA_HEBDO}")
    st.write("#### Choisir un étage")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("P1", use_container_width=True): st.session_state.etage_choisi="P1"; st.session_state.page="detail_etage"; st.rerun()
        if st.button("P3", use_container_width=True): st.session_state.etage_choisi="P3"; st.session_state.page="detail_etage"; st.rerun()
    with c2:
        if st.button("P2", use_container_width=True): st.session_state.etage_choisi="P2"; st.session_state.page="detail_etage"; st.rerun()
        if st.button("P4", use_container_width=True): st.session_state.etage_choisi="P4"; st.session_state.page="detail_etage"; st.rerun()
    st.markdown("---")
    st.write("#### Vos réservations")
    mes_resas = get_mes_reservations_futures(st.session_state.email)
    if not mes_resas: st.caption("Aucune.")
    else:
        now = datetime.datetime.now()
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        for r in mes_resas:
            try: d_obj = datetime.datetime.strptime(r[1], "%Y-%m-%d")
            except: d_obj = datetime.date.today()
            is_today = (r[1] == today_str)
            start_dt = datetime.datetime.strptime(f"{r[1]} {r[2]}", "%Y-%m-%d %H:%M")
            delta_minutes = (now - start_dt).total_seconds() / 60
            can_checkin = is_today and (-15 <= delta_minutes <= CHECKIN_TIME_MIN)
            confirmed_list = r[4].split(',') if r[4] else []
            is_confirmed_by_me = st.session_state.email in confirmed_list
            parts = r[6].split(',') if r[6] else []
            total_people = 1 + len(parts)
            with st.container():
                col_info, col_action = st.columns([3, 1])
                with col_info:
                    st.markdown(f"**{r[0]}** | {format_date_joli(d_obj)}")
                    st.caption(f"⏰ {r[2]} - {r[3]} | 👥 {total_people} pers.")
                    if not is_confirmed_by_me and is_today and can_checkin:
                        temps_restant = CHECKIN_TIME_MIN - delta_minutes
                        st.warning(f"⏳ Check-in requis ({int(temps_restant)} min)")
                    elif is_confirmed_by_me: st.success("✅ Validé (Vous)")
                with col_action:
                    if is_confirmed_by_me:
                        if st.button("🎫 Ticket", key=f"tick_{r[5]}"):
                            show_ticket({"salle": r[0], "date": r[1], "start": r[2], "end": r[3], "id": r[5]})
                    elif can_checkin:
                        if st.button("📍 Scanner", key=f"chk_{r[5]}", type="primary"):
                            confirm_reservation_user(r[5], st.session_state.email)
                            st.toast("Présence confirmée !"); st.rerun()
                    else: st.button("Attente...", disabled=True, key=f"wait_{r[5]}")
                st.divider()

def vue_detail_etage():
    if st.button("⬅️ Retour"): st.session_state.page="accueil"; st.rerun()
    st.write("") 
    col_gauche, col_droite = st.columns([1, 3], gap="large")
    etage = st.session_state.etage_choisi
    with col_gauche:
        st.markdown(f'<div class="red-card">{etage}</div>', unsafe_allow_html=True)
        cols_nav = st.columns(3)
        all_floors = ["P1", "P2", "P3", "P4"]
        others = [f for f in all_floors if f != etage]
        for i in range(3):
            if cols_nav[i].button(others[i], key=f"nav_{others[i]}", use_container_width=True):
                st.session_state.etage_choisi = others[i]; st.rerun()
    with col_droite:
        with st.container():
            c_d, c_h = st.columns([1, 2])
            today = datetime.date.today()
            if today.weekday() > 4: today += datetime.timedelta(days=(7-today.weekday()))
            jours_options, jours_map, curr = [], {}, today
            for i in range(5):
                l = format_date_joli(curr); jours_options.append(l); jours_map[l]=curr; curr+=datetime.timedelta(days=1); 
                while curr.weekday()>4: curr+=datetime.timedelta(days=1)
            choix_jour = c_d.selectbox("Date", options=jours_options, label_visibility="collapsed")
            now_h = datetime.datetime.now().hour
            def_h = now_h if 8 <= now_h <= 20 else 10
            h = c_h.slider("Heure", 8, 20, def_h, format="%dh", label_visibility="collapsed")
            st.write(""); st.write("") 
        st.write("#### Choisir un niveau :")
        is_forced_groupe = get_admin_config_groupe()
        if is_forced_groupe: st.warning("👥 **Forte affluence :** Groupes uniquement.")
        else: st.success("👤 **Calme :** Solo autorisé.")
        date_choisie = jours_map[choix_jour]
        time_choisi = datetime.time(h, 0)
        reservation_possible = (date_choisie == datetime.date.today())
        planning_jour = get_planning_sql(date_choisie)
        resas_db = get_db_reservations(date_choisie)
        salles_etage = sorted(list(set([c['salle'] for c in planning_jour if f"CC {etage}" in c['salle']])))
        groupes = {"Niveau Parking": [], "Niveau 0": [], "Niveau 1": []}
        for s in salles_etage:
            suffixe = s.replace(f"CC {etage} ", "")
            if "P" in suffixe: groupes["Niveau Parking"].append(s)
            elif suffixe.startswith("1"): groupes["Niveau 1"].append(s)
            else: groupes["Niveau 0"].append(s)
        for nom_grp, lst in groupes.items():
            if not lst: continue
            dispos = []
            for s in lst:
                color, fin, msg, force_local = analyse_salle_intelligente(s, planning_jour, resas_db, time_choisi, st.session_state.email, date_choisie)
                dispos.append({"s": s, "c": color, "f": fin, "m": msg, "g": force_local})
            nb_libres = len([d for d in dispos if d['c'] == 'vert'])
            icone = "🟢" if nb_libres > 0 else "🔴"
            is_open = (st.session_state.expanded_grp == nom_grp)
            with st.expander(f"{nom_grp} — {icone} {nb_libres} disponibles", expanded=is_open):
                cols_salles = st.columns(2)
                for i, d in enumerate(dispos):
                    nom_court = d['s'].replace(f"CC {etage} ", "")
                    icons_str = get_room_icons(d['s'])
                    with cols_salles[i % 2]:
                        if d['c'] == 'vert':
                            must_group = d['g'] or is_forced_groupe
                            btn_txt = f"👥 Créer Grp {nom_court}{icons_str}" if must_group else f"👤 {nom_court}{icons_str}"
                            if st.button(btn_txt, key=d['s'], use_container_width=True, disabled=not reservation_possible):
                                dt_debut = datetime.datetime.combine(date_choisie, time_choisi)
                                dt_fin_th = dt_debut + datetime.timedelta(hours=MAX_DUREE_HEURES)
                                dt_fin_cr = datetime.datetime.combine(date_choisie, d['f'])
                                fin_eff = min(dt_fin_th, dt_fin_cr).time()
                                st.session_state.expanded_grp = nom_grp
                                confirm_booking_dialog(st.session_state.email, d['s'], date_choisie, time_choisi, fin_eff, d['g'] or is_forced_groupe)
                        elif d['c'] == 'bleu':
                            if st.button(f"🔵 {d['m']}{icons_str}", key=d['s'], use_container_width=True, disabled=not reservation_possible):
                                stat, msg = manage_group_action(st.session_state.email, d['s'], date_choisie, time_choisi, "join")
                                st.session_state.expanded_grp = nom_grp
                                if stat == "error": st.error(msg)
                                elif msg: st.toast(msg)
                                st.rerun()
                        elif d['c'] == 'orange_moi':
                            if st.button(f"🟠 {d['m']}{icons_str}", key=d['s'], use_container_width=True, disabled=not reservation_possible):
                                action = "cancel" if "Annuler" in d['m'] else "leave"
                                stat, msg = manage_group_action(st.session_state.email, d['s'], date_choisie, time_choisi, action)
                                st.session_state.expanded_grp = nom_grp
                                if msg: st.toast(msg)
                                st.rerun()
                        elif d['c'] == 'admin_lock': st.error(f"{d['m']} {nom_court}")
                        else: st.warning(f"🔒 {nom_court} ({d['m']})")
        if not reservation_possible: st.caption("🔒 Réservation ouverte uniquement pour le jour même.")
        else: st.info("👆 Cliquez sur un niveau pour dérouler.")

if __name__ == "__main__":
    main()