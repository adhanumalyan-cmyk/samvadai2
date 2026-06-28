import os
import sys
import uuid
import time
import hmac
import hashlib
import requests
import base64
import re
import io
from datetime import datetime

from flask import Flask, request, jsonify, Response, stream_with_context, render_template_string
from flask_cors import CORS
from dotenv import load_dotenv
from groq import Groq

try:
    from gtts import gTTS
    GTTS_AVAILABLE = True
except ImportError:
    GTTS_AVAILABLE = False
    print("⚠️ gTTS not installed. Run: pip install gTTS")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, '.env'))

app = Flask(__name__)
CORS(app)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
AGORA_APP_ID = os.getenv("AGORA_APP_ID", "demo")
AGORA_CERT = os.getenv("AGORA_CERTIFICATE", "")

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY and GROQ_API_KEY.startswith('gsk_') else None
MODEL = "llama-3.3-70b-versatile"

convos = {}
cnt = 0
calls = {}

# Language Detection (Same as before - keeping it short for space, but full logic is needed)
TAMIL_SCRIPT = set('அஆஇஈஉஊஎஏஐஒஓஔகஙசஜஞடணதநபமயரலவழளறனஷஸஹ')
HINDI_SCRIPT = set('अआइईउऊएऐओऔकखगघचछजझटठडढणतथदधनपफबभमयरलवशषसह')

TAMIL_KEYWORDS = {
    'naan','nee','avan','aval','ivanga','avanga','unga','en','enakku','yennakku',
    'ennaku','enna','yaaru','eppadi','ippo','appo','apram','munadi',
    'pannu','pannunga','pannitu','panniruken','pota','pottu',
    'sollu','sollunga','sollitu','solren','sollathu',
    'pesu','pesanum','pesa','pesaren','pesunga',
    'poga','poren','ponga','poyitu','poyi',
    'vaa','vaanga','vandhu','vanthu','varen',
    'kelu','kelunga','ketta','kettathu',
    'paaru','paathinga','paathu','paakaren',
    'irukku','irukka','iruken','irukanga','illai','illa',
    'theriyum','theriyathu','therinja','therila',
    'mudiyum','mudiyathu','mudichu','mudinjathu',
    'venda','vendam','vendum','venum',
    'nalla','romba','konjam','mikka','neraya','sila','ella',
    'periya','sirya','pudhu','pazhaya','kettadhu',
    'velai','veedu','kadaisi','mudhal','rendu','moondru','naalu','aindhu',
    'oru','naalu','aindhu','aaru','ezhu','ettu','ombathu','pathu',
    'podhu','pothu','neram','veetla','office','shop','kadai',
    'seri','sari','aama','therla','puriyala','puriyuthu',
    'enga','inge','ange','engayum','athu','ithu','ethu',
    'yenakku','yenna','yeppadi','yengayo','yaruvadhu','yaravathu',
    'thevai','thevailla','paarkalaam','sollanam','kettukonga','pakkalaam',
    'vanakkam','namasthe','superam','machan','da','di','bro','akka','anna'
}

HINDI_KEYWORDS = {
    'aap','tum','mai','hum','usne','unhone','mujhe','tujhe','hamein',
    'kya','kaise','kab','kahan','kyu','kaun','kis','kiske',
    'hai','hain','hoon','the','thi','raha','rahi','rahe',
    'kar','karo','karna','karte','karta','karti','karega',
    'jao','jaana','jaate','jaega','aao','aana','aate','aega',
    'batana','batavo','batao','bataiye',
    'sunna','suno','suniye','dekho','dekha','dekhna',
    'acha','theek','sahi','galat','nahi','haan','ji','bhai','behan',
    'mera','tera','uska','humara','tumhara','apna',
    'chahiye','chahie','manga','mangta','dena','do','dunga',
    'abhi','kal','aaj','subah','shaam','raat','din',
    'yaar','dost','matlab','matlab','seedha','zyada','thoda',
    'bahut','bilkul','ekdum','zaroor','phir','toh','lekin','aur',
    'namaste','namaskar','kaam','paisa','help','karo','bolo'
}

def detect_language(text):
    text_lower = text.lower()
    text_clean = re.sub(r'[^a-z0-9 ]', ' ', text_lower)
    words = set(text_clean.split())
    
    tamil_script_count = sum(1 for c in text if c in TAMIL_SCRIPT)
    hindi_script_count = sum(1 for c in text if c in HINDI_SCRIPT)
    if tamil_script_count >= 2: return "Tamil"
    if hindi_script_count >= 2: return "Hindi"
    
    tamil_match_count = sum(1 for w in words if w in TAMIL_KEYWORDS)
    hindi_match_count = sum(1 for w in words if w in HINDI_KEYWORDS)
    
    if tamil_match_count < 2:
        for key in TAMIL_KEYWORDS:
            if len(key) > 3 and key in text_lower:
                tamil_match_count += 1
                if tamil_match_count >= 2: break
    if tamil_match_count >= 2: return "Tamil"
    if hindi_match_count >= 2: return "Hindi"
    return "English"

MODE_PROMPTS = {
    "sales": """You are an AGGRESSIVE but FRIENDLY Sales Agent at FlowZint.
Always capture lead details (Name, Phone, Company, Requirement) within 2-3 exchanges.
Reply ONLY in user's language. Keep replies SHORT: 2-3 sentences.""",
    "support": """You are a PATIENT Technical Support Agent at FlowZint.
Ask clear questions. Give step-by-step solutions. Reply ONLY in user's language.
Keep replies CONCISE: 3-4 sentences.""",
    "customer": """You are an EMPATHETIC Customer Care Agent at FlowZint.
Always apologize first. Offer solutions. Reply ONLY in user's language.
Short, human replies: 2-3 sentences."""
}

def gen_agora_token(channel, uid=0, role=1, expire_seconds=3600):
    if not AGORA_APP_ID or AGORA_APP_ID == "demo":
        return {"token": f"SIM_{channel}_{int(time.time())}", "app_id": AGORA_APP_ID, "channel": channel, "uid": uid, "simulated": True}
    try:
        VERSION = "007"
        privilege_expired_ts = int(time.time()) + expire_seconds
        PRIVILEGE_JOIN_CHANNEL = 1
        PRIVILEGE_PUBLISH_AUDIO_STREAM = 2
        PRIVILEGE_PUBLISH_VIDEO_STREAM = 3
        PRIVILEGE_PUBLISH_DATA_STREAM = 4
        privileges = {
            PRIVILEGE_JOIN_CHANNEL: privilege_expired_ts,
            PRIVILEGE_PUBLISH_AUDIO_STREAM: privilege_expired_ts,
            PRIVILEGE_PUBLISH_VIDEO_STREAM: privilege_expired_ts,
            PRIVILEGE_PUBLISH_DATA_STREAM: privilege_expired_ts
        }
        nonce = uuid.uuid4().hex
        ts = int(time.time())
        import struct
        def pack_uint16(x): return struct.pack('<H', int(x))
        def pack_uint32(x): return struct.pack('<I', int(x))
        def pack_string(s):
            b = s.encode('utf-8')
            return pack_uint16(len(b)) + b
        def pack_map_uint32(d):
            result = pack_uint16(len(d))
            for k, v in sorted(d.items()):
                result += pack_uint16(k) + pack_uint32(v)
            return result
        msg = pack_uint32(ts) + pack_uint32(0) + pack_string(nonce) + pack_map_uint32(privileges)
        signing_key = hmac.new(AGORA_CERT.encode('utf-8'), AGORA_APP_ID.encode('utf-8'), hashlib.sha256).digest()
        signing_key = hmac.new(signing_key, str(ts).encode('utf-8'), hashlib.sha256).digest()
        signing_key = hmac.new(signing_key, nonce.encode('utf-8'), hashlib.sha256).digest()
        signing_key = hmac.new(signing_key, str(uid).encode('utf-8'), hashlib.sha256).digest()
        signing_key = hmac.new(signing_key, channel.encode('utf-8'), hashlib.sha256).digest()
        signature = hmac.new(signing_key, msg, hashlib.sha256).digest()
        content = (
            pack_string(AGORA_APP_ID) + pack_string(channel) + pack_string(str(uid)) +
            pack_string(nonce) + pack_uint32(ts) + pack_uint16(len(privileges))
        )
        for k, v in sorted(privileges.items()):
            content += pack_uint16(k) + pack_uint32(v)
        content += pack_uint16(len(signature)) + signature
        token = VERSION + base64.b64encode(content).decode('utf-8')
        return {"token": token, "app_id": AGORA_APP_ID, "channel": channel, "uid": uid, "simulated": False, "expires_at": privilege_expired_ts}
    except Exception as e:
        print(f"Agora token error: {e}")
        return {"token": f"TOKEN_{channel}_{int(time.time())}", "app_id": AGORA_APP_ID, "channel": channel, "uid": uid, "simulated": True}

# ============================================================
# UI HTML – CONTINUOUS CONVERSATION MODE
# ============================================================
UI_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Samvad AI — Multilingual Voice AI</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<style>
:root { --bg: #0F0E23; --bg2: #13122a; --purple: #6C3BF5; --cyan: #00D4FF; --purple-light: #a78bfa; --white: #ffffff; --glass: rgba(255,255,255,0.04); --glass-border: rgba(255,255,255,0.08); --glass-border-purple: rgba(108,59,245,0.35); }
* { margin:0; padding:0; box-sizing:border-box; }
html { scroll-behavior:smooth; }
body { background:var(--bg); color:var(--white); font-family:'Inter',sans-serif; overflow-x:hidden; }
#bg-canvas { position:fixed; top:0; left:0; width:100%; height:100%; z-index:0; pointer-events:none; }
.page { position:relative; z-index:1; }
nav { position:fixed; top:0; left:0; right:0; z-index:1000; display:flex; align-items:center; justify-content:space-between; padding:0 60px; height:68px; background:rgba(15,14,35,0.75); backdrop-filter:blur(20px); border-bottom:1px solid rgba(108,59,245,0.15); }
.nav-logo { font-family:'Space Grotesk',sans-serif; font-size:22px; font-weight:700; background:linear-gradient(135deg,#6C3BF5,#00D4FF); -webkit-background-clip:text; -webkit-text-fill-color:transparent; letter-spacing:-0.5px; }
.nav-links { display:flex; align-items:center; gap:8px; }
.nav-links a { color:rgba(255,255,255,0.6); text-decoration:none; font-size:14px; padding:8px 16px; border-radius:8px; transition:all 0.2s; cursor:pointer; }
.nav-links a:hover { color:#fff; background:rgba(255,255,255,0.05); }
.nav-links a.active { color:var(--cyan); }
.nav-cta { background:linear-gradient(135deg,#6C3BF5,#00D4FF) !important; color:#fff !important; -webkit-text-fill-color:#fff !important; padding:9px 22px !important; border-radius:25px !important; font-weight:600 !important; }
section { min-height:100vh; padding:100px 60px 80px; display:none; }
section.active { display:block; }
#landing { display:flex; align-items:center; justify-content:space-between; gap:60px; padding-top:120px; }
.hero-left { flex:1; max-width:580px; }
.hero-badge { display:inline-flex; align-items:center; gap:8px; background:rgba(108,59,245,0.12); border:1px solid rgba(108,59,245,0.35); border-radius:20px; padding:7px 16px; font-size:13px; color:var(--purple-light); margin-bottom:28px; }
.badge-dot { width:7px; height:7px; background:var(--purple); border-radius:50%; animation:badgePulse 2s infinite; }
@keyframes badgePulse { 0%,100%{opacity:1;box-shadow:0 0 0 0 rgba(108,59,245,0.4)} 50%{opacity:0.6;box-shadow:0 0 0 6px rgba(108,59,245,0)} }
h1.hero-title { font-family:'Space Grotesk',sans-serif; font-size:clamp(50px,6vw,80px); font-weight:700; line-height:1.04; letter-spacing:-2px; margin-bottom:22px; }
.grad { background:linear-gradient(135deg,#6C3BF5 0%,#00D4FF 60%,#a78bfa 100%); -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-size:200%; animation:gradShift 5s ease infinite; }
@keyframes gradShift { 0%,100%{background-position:0%} 50%{background-position:100%} }
.hero-tagline { font-size:18px; color:rgba(255,255,255,0.55); line-height:1.65; margin-bottom:44px; }
.hero-btns { display:flex; gap:16px; flex-wrap:wrap; }
.btn-primary { background:linear-gradient(135deg,#6C3BF5,#00D4FF); border:none; color:#fff; padding:15px 36px; border-radius:50px; font-size:15px; font-weight:600; cursor:pointer; box-shadow:0 0 30px rgba(108,59,245,0.35); transition:all 0.3s; font-family:'Inter',sans-serif; }
.btn-primary:hover { box-shadow:0 0 55px rgba(108,59,245,0.6); transform:translateY(-2px); }
.btn-ghost { background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.12); color:#fff; padding:15px 36px; border-radius:50px; font-size:15px; font-weight:500; cursor:pointer; transition:all 0.3s; font-family:'Inter',sans-serif; }
.btn-ghost:hover { background:rgba(255,255,255,0.08); border-color:rgba(108,59,245,0.4); }
.hero-right { flex:1; display:flex; align-items:center; justify-content:center; min-height:500px; position:relative; }
.sphere-canvas-wrap { position:relative; width:420px; height:420px; }
#hero-canvas { width:420px; height:420px; border-radius:50%; }
.sphere-label { position:absolute; top:50%; left:50%; transform:translate(-50%,-50%); text-align:center; pointer-events:none; }
.sphere-label span { font-family:'Space Grotesk',sans-serif; font-size:26px; font-weight:700; background:linear-gradient(135deg,#fff,#00D4FF); -webkit-background-clip:text; -webkit-text-fill-color:transparent; display:block; }
.orbit-wrap { position:absolute; inset:0; pointer-events:none; }
.orbit-icon { position:absolute; width:48px; height:48px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:20px; background:rgba(108,59,245,0.2); border:1px solid rgba(108,59,245,0.4); backdrop-filter:blur(10px); }
.o1{top:10%;left:50%;animation:orbit1 6s linear infinite}
.o2{top:50%;left:5%;animation:orbit2 7s linear infinite}
.o3{top:80%;left:40%;animation:orbit3 8s linear infinite}
.o4{top:30%;left:85%;animation:orbit4 5s linear infinite}
@keyframes orbit1{0%,100%{transform:translate(-50%,-50%) translateY(-30px)}50%{transform:translate(-50%,-50%) translateY(30px)}}
@keyframes orbit2{0%,100%{transform:translate(0,0) rotate(0deg)}50%{transform:translate(20px,-20px) rotate(180deg)}}
@keyframes orbit3{0%,100%{transform:translate(0,0)}50%{transform:translate(-20px,-30px)}}
@keyframes orbit4{0%,100%{transform:translate(0,0) scale(1)}50%{transform:translate(-15px,15px) scale(1.15)}}
.stats-bar { display:flex; justify-content:center; border-top:1px solid rgba(255,255,255,0.05); border-bottom:1px solid rgba(255,255,255,0.05); background:rgba(0,0,0,0.2); }
.stat-item { flex:1; text-align:center; padding:36px 20px; border-right:1px solid rgba(255,255,255,0.06); }
.stat-item:last-child { border-right:none; }
.stat-num { font-family:'Space Grotesk',sans-serif; font-size:38px; font-weight:700; background:linear-gradient(135deg,#6C3BF5,#00D4FF); -webkit-background-clip:text; -webkit-text-fill-color:transparent; display:block; }
.stat-label { font-size:13px; color:rgba(255,255,255,0.45); margin-top:6px; }
.sec-title { font-family:'Space Grotesk',sans-serif; font-size:clamp(34px,4vw,52px); font-weight:700; letter-spacing:-1px; margin-bottom:14px; text-align:center; }
.sec-sub { font-size:16px; color:rgba(255,255,255,0.5); text-align:center; margin-bottom:64px; line-height:1.6; }
#features { display:block; min-height:100vh; padding:120px 60px 80px; }
.feature-grid { display:grid; grid-template-columns:repeat(2,1fr); gap:24px; max-width:1000px; margin:0 auto; }
.feat-card { background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.07); border-radius:24px; padding:40px 36px; position:relative; overflow:hidden; cursor:default; transition:all 0.4s cubic-bezier(0.23,1,0.32,1); }
.feat-card::before { content:''; position:absolute; inset:0; border-radius:24px; background:linear-gradient(135deg,rgba(108,59,245,0.08),rgba(0,212,255,0.04)); opacity:0; transition:opacity 0.4s; }
.feat-card:hover { border-color:rgba(108,59,245,0.4); transform:translateY(-8px) perspective(600px) rotateX(2deg); box-shadow:0 30px 80px rgba(108,59,245,0.2); }
.feat-card:hover::before { opacity:1; }
.feat-icon-3d { width:70px; height:70px; border-radius:18px; display:flex; align-items:center; justify-content:center; font-size:32px; margin-bottom:24px; }
.fi-p { background:rgba(108,59,245,0.18); border:1px solid rgba(108,59,245,0.3); box-shadow:0 8px 32px rgba(108,59,245,0.2); }
.fi-c { background:rgba(0,212,255,0.12); border:1px solid rgba(0,212,255,0.25); box-shadow:0 8px 32px rgba(0,212,255,0.15); }
.fi-m { background:rgba(236,72,153,0.12); border:1px solid rgba(236,72,153,0.25); box-shadow:0 8px 32px rgba(236,72,153,0.15); }
.fi-g { background:rgba(52,211,153,0.12); border:1px solid rgba(52,211,153,0.25); box-shadow:0 8px 32px rgba(52,211,153,0.15); }
.feat-card h3 { font-family:'Space Grotesk',sans-serif; font-size:22px; font-weight:600; margin-bottom:12px; }
.feat-card p { font-size:15px; color:rgba(255,255,255,0.5); line-height:1.7; }
.feat-tag { display:inline-block; margin-top:20px; padding:5px 14px; border-radius:20px; font-size:12px; font-weight:500; background:rgba(108,59,245,0.15); color:var(--purple-light); border:1px solid rgba(108,59,245,0.25); }
#dashboard { display:block; min-height:100vh; padding:100px 0 0; }
.dash-layout { display:flex; height:calc(100vh - 100px); }
.dash-sidebar { width:240px; background:rgba(0,0,0,0.4); border-right:1px solid rgba(255,255,255,0.05); backdrop-filter:blur(20px); padding:30px 0; flex-shrink:0; }
.dash-logo { padding:0 24px 30px; font-family:'Space Grotesk',sans-serif; font-size:20px; font-weight:700; background:linear-gradient(135deg,#6C3BF5,#00D4FF); -webkit-background-clip:text; -webkit-text-fill-color:transparent; border-bottom:1px solid rgba(255,255,255,0.05); margin-bottom:20px; }
.dash-nav-item { display:flex; align-items:center; gap:12px; padding:12px 24px; font-size:14px; color:rgba(255,255,255,0.5); cursor:pointer; transition:all 0.2s; border-left:3px solid transparent; }
.dash-nav-item:hover { color:#fff; background:rgba(108,59,245,0.08); }
.dash-nav-item.active { color:var(--cyan); border-left-color:var(--cyan); background:rgba(0,212,255,0.06); }
.dash-icon { font-size:18px; }
.dash-main { flex:1; padding:30px 36px; overflow-y:auto; }
.dash-header { display:flex; align-items:center; justify-content:space-between; margin-bottom:30px; }
.dash-welcome h2 { font-family:'Space Grotesk',sans-serif; font-size:24px; font-weight:600; }
.dash-welcome p { font-size:14px; color:rgba(255,255,255,0.45); margin-top:4px; }
.dash-actions { display:flex; align-items:center; gap:16px; }
.notif-btn { position:relative; width:40px; height:40px; border-radius:50%; background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.08); display:flex; align-items:center; justify-content:center; cursor:pointer; font-size:18px; }
.notif-badge { position:absolute; top:-2px; right:-2px; width:14px; height:14px; background:var(--purple); border-radius:50%; font-size:9px; display:flex; align-items:center; justify-content:center; border:2px solid var(--bg); }
.avatar { width:40px; height:40px; border-radius:50%; background:linear-gradient(135deg,#6C3BF5,#00D4FF); display:flex; align-items:center; justify-content:center; font-size:16px; font-weight:600; cursor:pointer; }
.stat-cards { display:grid; grid-template-columns:repeat(4,1fr); gap:18px; margin-bottom:28px; }
.stat-card { background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.06); border-radius:18px; padding:22px; transition:all 0.3s; position:relative; overflow:hidden; }
.stat-card::after { content:''; position:absolute; bottom:-20px; right:-20px; width:80px; height:80px; border-radius:50%; opacity:0.06; }
.stat-card.sc1::after{background:#6C3BF5}.stat-card.sc2::after{background:#00D4FF}.stat-card.sc3::after{background:#a78bfa}.stat-card.sc4::after{background:#34d399}
.stat-card:hover { border-color:rgba(108,59,245,0.3); transform:translateY(-4px); box-shadow:0 16px 40px rgba(0,0,0,0.3); }
.sc-top { display:flex; align-items:center; justify-content:space-between; margin-bottom:14px; }
.sc-label { font-size:13px; color:rgba(255,255,255,0.45); }
.sc-ico { font-size:22px; }
.sc-val { font-family:'Space Grotesk',sans-serif; font-size:30px; font-weight:700; }
.sc1 .sc-val{background:linear-gradient(135deg,#6C3BF5,#a78bfa);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.sc2 .sc-val{background:linear-gradient(135deg,#00D4FF,#0ea5e9);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.sc3 .sc-val{background:linear-gradient(135deg,#a78bfa,#ec4899);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.sc4 .sc-val{background:linear-gradient(135deg,#34d399,#06b6d4);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.sc-change { font-size:12px; color:#34d399; margin-top:6px; }
.dash-grid-2 { display:grid; grid-template-columns:1fr 1fr; gap:20px; }
.dash-panel { background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.06); border-radius:18px; padding:24px; }
.panel-title { font-family:'Space Grotesk',sans-serif; font-size:16px; font-weight:600; margin-bottom:20px; color:rgba(255,255,255,0.85); }
.lang-row { margin-bottom:16px; }
.lang-info { display:flex; justify-content:space-between; font-size:13px; margin-bottom:8px; }
.lang-name { color:rgba(255,255,255,0.7); }
.lang-pct { color:var(--purple-light); font-weight:500; }
.lang-bar-bg { height:6px; background:rgba(255,255,255,0.06); border-radius:3px; overflow:hidden; }
.lang-bar { height:100%; border-radius:3px; animation:barGrow 1.5s ease forwards; transform-origin:left; }
@keyframes barGrow{from{width:0%}}
.lb1{background:linear-gradient(90deg,#6C3BF5,#00D4FF)}.lb2{background:linear-gradient(90deg,#a78bfa,#6C3BF5)}.lb3{background:linear-gradient(90deg,#00D4FF,#06b6d4)}.lb4{background:linear-gradient(90deg,#ec4899,#a78bfa)}.lb5{background:linear-gradient(90deg,#34d399,#00D4FF)}
.conv-item { display:flex; align-items:center; gap:12px; padding:12px 0; border-bottom:1px solid rgba(255,255,255,0.04); }
.conv-item:last-child{border-bottom:none}
.conv-avatar { width:36px; height:36px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:14px; font-weight:600; flex-shrink:0; }
.ca1{background:rgba(108,59,245,0.25)}.ca2{background:rgba(0,212,255,0.2)}.ca3{background:rgba(236,72,153,0.2)}.ca4{background:rgba(52,211,153,0.2)}
.conv-info{flex:1}
.conv-name{font-size:14px;font-weight:500}
.conv-preview{font-size:12px;color:rgba(255,255,255,0.4);margin-top:2px}
.conv-badge{padding:3px 10px;border-radius:12px;font-size:11px;font-weight:500}
.cb-ta{background:rgba(52,211,153,0.15);color:#34d399}.cb-hi{background:rgba(108,59,245,0.15);color:var(--purple-light)}.cb-en{background:rgba(0,212,255,0.12);color:var(--cyan)}.cb-ml{background:rgba(236,72,153,0.12);color:#ec4899}
.fab { position:fixed; bottom:36px; right:36px; width:60px; height:60px; border-radius:50%; background:linear-gradient(135deg,#6C3BF5,#00D4FF); border:none; cursor:pointer; font-size:26px; display:flex; align-items:center; justify-content:center; box-shadow:0 0 30px rgba(108,59,245,0.5); animation:fabPulse 2.5s ease-in-out infinite; z-index:999; transition:transform 0.2s; }
.fab:hover{transform:scale(1.1)}
@keyframes fabPulse{0%,100%{box-shadow:0 0 30px rgba(108,59,245,0.5)}50%{box-shadow:0 0 60px rgba(108,59,245,0.8),0 0 100px rgba(0,212,255,0.3)}}
#chat { display:block; min-height:100vh; padding:100px 0 0; }
.chat-layout { height:calc(100vh - 100px); display:flex; flex-direction:column; }
.chat-topbar { display:flex; align-items:center; justify-content:space-between; padding:16px 32px; background:rgba(0,0,0,0.3); border-bottom:1px solid rgba(255,255,255,0.05); backdrop-filter:blur(20px); }
.mode-selector { display:flex; gap:8px; }
.mode-btn { padding:7px 18px; border-radius:20px; font-size:13px; font-weight:500; cursor:pointer; border:1px solid rgba(255,255,255,0.08); background:transparent; color:rgba(255,255,255,0.5); transition:all 0.2s; font-family:'Inter',sans-serif; }
.mode-btn.active { background:linear-gradient(135deg,#6C3BF5,#00D4FF); border-color:transparent; color:#fff; }
.lang-indicator { display:flex; align-items:center; gap:10px; font-size:13px; color:rgba(255,255,255,0.6); }
.lang-orb { width:10px; height:10px; border-radius:50%; background:var(--cyan); animation:langOrb 2s ease-in-out infinite; }
@keyframes langOrb{0%,100%{box-shadow:0 0 0 0 rgba(0,212,255,0.5)}50%{box-shadow:0 0 0 6px rgba(0,212,255,0)}}
.chat-messages { flex:1; overflow-y:auto; padding:24px 40px; display:flex; flex-direction:column; gap:20px; }
.chat-messages::-webkit-scrollbar{width:4px}
.chat-messages::-webkit-scrollbar-track{background:transparent}
.chat-messages::-webkit-scrollbar-thumb{background:rgba(108,59,245,0.3);border-radius:2px}
.msg { display:flex; gap:12px; max-width:70%; animation:msgSlide 0.4s ease; }
@keyframes msgSlide{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:translateY(0)}}
.msg.user { align-self:flex-end; flex-direction:row-reverse; }
.msg-avatar { width:36px; height:36px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:16px; flex-shrink:0; background:rgba(108,59,245,0.2); }
.msg-bubble { padding:14px 18px; border-radius:18px; font-size:14px; line-height:1.6; }
.msg.ai .msg-bubble { background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.07); border-radius:4px 18px 18px 18px; color:rgba(255,255,255,0.85); }
.msg.user .msg-bubble { background:linear-gradient(135deg,#6C3BF5,#5b21b6); border-radius:18px 4px 18px 18px; color:#fff; }
.msg-lang { font-size:11px; margin-top:6px; color:rgba(255,255,255,0.35); }
.typing-bubble { display:flex; align-items:center; gap:6px; padding:14px 18px; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.07); border-radius:4px 18px 18px 18px; }
.t-dot { width:8px; height:8px; border-radius:50%; background:var(--purple-light); animation:tDot 1.2s ease-in-out infinite; }
.t-dot:nth-child(2){animation-delay:0.2s}.t-dot:nth-child(3){animation-delay:0.4s}
@keyframes tDot{0%,80%,100%{transform:scale(0.6);opacity:0.3}40%{transform:scale(1);opacity:1}}
.chat-input-area { padding:20px 32px; background:rgba(0,0,0,0.3); border-top:1px solid rgba(255,255,255,0.05); display:flex; align-items:center; gap:12px; position:relative; }
.chat-input-box { flex:1; background:rgba(255,255,255,0.04); border:1px solid rgba(108,59,245,0.3); border-radius:28px; padding:14px 22px; color:#fff; font-size:14px; font-family:'Inter',sans-serif; outline:none; transition:border 0.2s; }
.chat-input-box:focus { border-color:#6C3BF5; box-shadow:0 0 0 3px rgba(108,59,245,0.1); }
.chat-input-box::placeholder{color:rgba(255,255,255,0.25)}
.send-btn { width:46px; height:46px; border-radius:50%; background:linear-gradient(135deg,#6C3BF5,#00D4FF); border:none; color:#fff; font-size:18px; cursor:pointer; display:flex; align-items:center; justify-content:center; transition:all 0.2s; box-shadow:0 0 20px rgba(108,59,245,0.4); }
.send-btn:hover { transform:scale(1.1); box-shadow:0 0 35px rgba(108,59,245,0.6); }

.mic-btn { width:46px; height:46px; border-radius:50%; background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.1); color:#fff; font-size:20px; cursor:pointer; display:flex; align-items:center; justify-content:center; transition:all 0.2s; position:relative; z-index:2; flex-shrink:0; }
.mic-btn:hover { background:rgba(108,59,245,0.2); border-color:rgba(108,59,245,0.4); }
.mic-btn.jarvis-active { background:rgba(108,59,245,0.3); border-color:rgba(108,59,245,0.8); box-shadow:0 0 0 0 rgba(108,59,245,0.6); animation:jarvisMicPulse 0.8s ease-in-out infinite; }
@keyframes jarvisMicPulse { 0%{box-shadow:0 0 0 0 rgba(108,59,245,0.7),0 0 0 0 rgba(0,212,255,0.4)} 70%{box-shadow:0 0 0 14px rgba(108,59,245,0),0 0 0 26px rgba(0,212,255,0)} 100%{box-shadow:0 0 0 0 rgba(108,59,245,0),0 0 0 0 rgba(0,212,255,0)} }

#jarvis-overlay { display:none; position:fixed; inset:0; z-index:9999; background:rgba(8,7,20,0.92); backdrop-filter:blur(12px); flex-direction:column; align-items:center; justify-content:center; gap:20px; }
#jarvis-overlay.active { display:flex; }
.jarvis-ring-wrap { position:relative; width:280px; height:280px; display:flex; align-items:center; justify-content:center; }
.jarvis-ring { position:absolute; border-radius:50%; border-style:solid; border-color:transparent; animation-timing-function:linear; animation-iteration-count:infinite; }
.jr1 { width:280px; height:280px; border-width:2px; border-top-color:rgba(108,59,245,0.9); border-right-color:rgba(108,59,245,0.2); animation:jarvisSpin1 1.4s linear infinite; }
.jr2 { width:240px; height:240px; border-width:1.5px; border-top-color:rgba(0,212,255,0.8); border-left-color:rgba(0,212,255,0.2); animation:jarvisSpin2 2s linear infinite; }
.jr3 { width:200px; height:200px; border-width:1px; border-top-color:rgba(167,139,250,0.7); border-right-color:rgba(167,139,250,0.15); animation:jarvisSpin1 2.8s linear infinite reverse; }
.jr4 { width:160px; height:160px; border-width:1.5px; border-top-color:rgba(0,212,255,0.5); border-left-color:rgba(0,212,255,0.1); animation:jarvisSpin2 1.8s linear infinite; }
@keyframes jarvisSpin1 { to{transform:rotate(360deg)} }
@keyframes jarvisSpin2 { to{transform:rotate(-360deg)} }
.jarvis-core { position:relative; z-index:2; width:90px; height:90px; border-radius:50%; background:radial-gradient(circle, rgba(108,59,245,0.4) 0%, rgba(0,212,255,0.15) 60%, transparent 100%); display:flex; align-items:center; justify-content:center; font-size:36px; animation:jarvisCorePulse 1.2s ease-in-out infinite; }
@keyframes jarvisCorePulse { 0%,100%{transform:scale(1);filter:brightness(1)} 50%{transform:scale(1.08);filter:brightness(1.4)} }
.jarvis-wave-bars { display:flex; align-items:center; gap:5px; height:50px; }
.jarvis-bar { width:5px; border-radius:3px; background:linear-gradient(to top,#6C3BF5,#00D4FF); animation:jarvisBarAnim 0.6s ease-in-out infinite alternate; transform-origin:bottom; }
.jarvis-bar:nth-child(1){height:12px;animation-delay:0s}
.jarvis-bar:nth-child(2){height:26px;animation-delay:0.08s}
.jarvis-bar:nth-child(3){height:40px;animation-delay:0.16s}
.jarvis-bar:nth-child(4){height:50px;animation-delay:0.24s}
.jarvis-bar:nth-child(5){height:38px;animation-delay:0.32s}
.jarvis-bar:nth-child(6){height:46px;animation-delay:0.40s}
.jarvis-bar:nth-child(7){height:30px;animation-delay:0.48s}
.jarvis-bar:nth-child(8){height:18px;animation-delay:0.56s}
@keyframes jarvisBarAnim { from{transform:scaleY(0.3);opacity:0.4} to{transform:scaleY(1);opacity:1} }
.jarvis-bar.idle { animation:none; transform:scaleY(0.25); opacity:0.3; }
.jarvis-status-text { font-family:'Space Grotesk',sans-serif; font-size:22px; font-weight:600; background:linear-gradient(135deg,#a78bfa,#00D4FF); -webkit-background-clip:text; -webkit-text-fill-color:transparent; letter-spacing:0.5px; text-align:center; }
.jarvis-sub-text { font-size:14px; color:rgba(255,255,255,0.4); text-align:center; margin-top:-20px; }
.jarvis-close-btn { padding:10px 28px; border-radius:24px; background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.1); color:rgba(255,255,255,0.55); font-size:14px; cursor:pointer; font-family:'Inter',sans-serif; transition:all 0.2s; }
.jarvis-close-btn:hover { background:rgba(255,255,255,0.1); color:#fff; }
#jarvis-send-btn { background:linear-gradient(135deg,#6C3BF5,#00D4FF) !important; color:#fff !important; border:none !important; display:none; }
#jarvis-send-btn:hover { transform:scale(1.05); }
.jr-dot { position:absolute; width:8px; height:8px; border-radius:50%; top:50%; left:50%; transform-origin:0 0; }
.jr-dot-1 { background:#6C3BF5; animation:jarvisDotOrbit1 1.4s linear infinite; }
.jr-dot-2 { background:#00D4FF; animation:jarvisDotOrbit2 2s linear infinite; }
@keyframes jarvisDotOrbit1 { 0%   { transform:rotate(0deg)   translateX(136px) translateY(-4px); } 100% { transform:rotate(360deg) translateX(136px) translateY(-4px); } }
@keyframes jarvisDotOrbit2 { 0%   { transform:rotate(0deg)   translateX(116px) translateY(-4px); } 100% { transform:rotate(-360deg) translateX(116px) translateY(-4px); } }

#footer-sec { display:block; min-height:auto; padding:0; }
.footer-glow-line { height:1px; background:linear-gradient(90deg,transparent,#6C3BF5,#00D4FF,transparent); }
.footer-body { background:rgba(0,0,0,0.4); padding:60px 60px 40px; }
.footer-top { display:grid; grid-template-columns:2fr 1fr 1fr 1fr; gap:40px; margin-bottom:50px; }
.footer-logo { font-family:'Space Grotesk',sans-serif; font-size:24px; font-weight:700; background:linear-gradient(135deg,#6C3BF5,#00D4FF); -webkit-background-clip:text; -webkit-text-fill-color:transparent; margin-bottom:14px; }
.footer-brand p { font-size:14px; color:rgba(255,255,255,0.4); line-height:1.7; max-width:280px; margin-bottom:20px; }
.footer-socials { display:flex; gap:10px; }
.social-btn { width:38px; height:38px; border-radius:50%; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08); display:flex; align-items:center; justify-content:center; font-size:16px; cursor:pointer; transition:all 0.2s; text-decoration:none; }
.social-btn:hover { background:rgba(108,59,245,0.2); border-color:rgba(108,59,245,0.4); }
.footer-col h4 { font-size:14px; font-weight:600; margin-bottom:20px; color:rgba(255,255,255,0.7); }
.footer-col a { display:block; font-size:14px; color:rgba(255,255,255,0.4); text-decoration:none; margin-bottom:12px; transition:color 0.2s; }
.footer-col a:hover { color:var(--cyan); }
.footer-bottom { display:flex; align-items:center; justify-content:space-between; padding-top:30px; border-top:1px solid rgba(255,255,255,0.05); flex-wrap:wrap; gap:16px; }
.footer-copy { font-size:13px; color:rgba(255,255,255,0.3); }
.powered-badge { display:inline-flex; align-items:center; gap:8px; background:rgba(108,59,245,0.1); border:1px solid rgba(108,59,245,0.25); border-radius:20px; padding:8px 20px; font-size:13px; color:rgba(255,255,255,0.5); }
.powered-badge strong { color:var(--purple-light); }
.section-transition { animation:secIn 0.5s ease; }
@keyframes secIn{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}
::-webkit-scrollbar{width:6px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:rgba(108,59,245,0.4);border-radius:3px}
</style>
</head>
<body>
<canvas id="bg-canvas"></canvas>

<div id="jarvis-overlay">
  <div class="jarvis-ring-wrap">
    <div class="jarvis-ring jr1"></div><div class="jarvis-ring jr2"></div><div class="jarvis-ring jr3"></div><div class="jarvis-ring jr4"></div>
    <div class="jr-dot jr-dot-1"></div><div class="jr-dot jr-dot-2"></div>
    <div class="jarvis-core" id="jarvis-core-icon">🎙️</div>
  </div>
  <div class="jarvis-wave-bars" id="jarvis-bars">
    <div class="jarvis-bar idle"></div><div class="jarvis-bar idle"></div><div class="jarvis-bar idle"></div><div class="jarvis-bar idle"></div>
    <div class="jarvis-bar idle"></div><div class="jarvis-bar idle"></div><div class="jarvis-bar idle"></div><div class="jarvis-bar idle"></div>
  </div>
  <div class="jarvis-status-text" id="jarvis-status">Initializing...</div>
  <div class="jarvis-sub-text" id="jarvis-sub">Tamil · Hindi · English supported</div>
  <div style="display:flex; gap:12px; margin-top:8px;">
    <button class="jarvis-close-btn" id="jarvis-send-btn">📤 Send</button>
    <button class="jarvis-close-btn" onclick="cancelJarvis()">✕ End Conversation</button>
  </div>
</div>

<nav>
  <div class="nav-logo">⚡ Samvad AI</div>
  <div class="nav-links">
    <a onclick="showSection('landing')" class="active" id="nav-landing">Home</a>
    <a onclick="showSection('features')" id="nav-features">Features</a>
    <a onclick="showSection('dashboard')" id="nav-dashboard">Dashboard</a>
    <a onclick="showSection('chat')" id="nav-chat">Chat</a>
    <a onclick="showSection('footer-sec')" id="nav-footer-sec">About</a>
    <a onclick="showSection('chat')" class="nav-cta">Start Free →</a>
  </div>
</nav>

<div class="page">
<section id="landing" class="active">
  <div class="hero-left">
    <div class="hero-badge"><span class="badge-dot"></span> Now live in India 🇮🇳 · FlowZint AI Hackathon 2026</div>
    <h1 class="hero-title"><span class="grad">Samvad AI</span><br>Talk to the<br>Future.</h1>
    <p class="hero-tagline">AI-Powered Business Communication for India.<br>Multi-language · Real-time · Intelligent · Built for Bharat.</p>
    <div class="hero-btns">
      <button class="btn-primary" onclick="showSection('chat')">Start Chatting 🚀</button>
      <button class="btn-ghost" onclick="showSection('features')">See Features</button>
    </div>
  </div>
  <div class="hero-right">
    <div class="sphere-canvas-wrap">
      <canvas id="hero-canvas"></canvas>
      <div class="sphere-label"><span>Samvad</span><span style="font-size:14px;color:rgba(255,255,255,0.5);font-family:'Inter';font-weight:400;margin-top:4px;">AI Platform</span></div>
      <div class="orbit-wrap">
        <div class="orbit-icon o1">💬</div><div class="orbit-icon o2">🎙️</div><div class="orbit-icon o3">🌐</div><div class="orbit-icon o4">🤖</div>
      </div>
    </div>
  </div>
</section>

<div id="stats-bar" class="stats-bar" style="display:none;">
  <div class="stat-item"><span class="stat-num" id="stat-convos">1M+</span><div class="stat-label">Conversations</div></div>
  <div class="stat-item"><span class="stat-num">99%</span><div class="stat-label">Uptime</div></div>
  <div class="stat-item"><span class="stat-num">6+</span><div class="stat-label">Languages</div></div>
  <div class="stat-item"><span class="stat-num">500+</span><div class="stat-label">Businesses</div></div>
</div>

<section id="features">
  <h2 class="sec-title">Why <span class="grad">Samvad AI?</span></h2>
  <p class="sec-sub">Built ground-up for Indian businesses. Every feature designed for Bharat.</p>
  <div class="feature-grid">
    <div class="feat-card"><div class="feat-icon-3d fi-p">🌐</div><h3>6+ Indian Languages</h3><p>Auto-detect and respond in Tamil, Hindi, Kannada, Telugu, Malayalam and more. Even Tanglish/Hinglish!</p><span class="feat-tag">NLP Engine v3</span></div>
    <div class="feat-card"><div class="feat-icon-3d fi-c">🎙️</div><h3>Speech-to-Speech</h3><p>Speak in your language. AI listens and speaks back in the same language. Jarvis-style experience.</p><span class="feat-tag">Real-time Voice</span></div>
    <div class="feat-card"><div class="feat-icon-3d fi-m">🤖</div><h3>Smart AI Agents</h3><p>Sales, Support, Customer Care — three specialized AI modes that adapt their persona automatically.</p><span class="feat-tag">3 Agent Modes</span></div>
    <div class="feat-card"><div class="feat-icon-3d fi-g">⚡</div><h3>Real-time Analytics</h3><p>Track conversations, leads, and resolution rates on a beautiful dashboard. Insights delivered live.</p><span class="feat-tag">Live Dashboard</span></div>
  </div>
</section>

<section id="dashboard">
  <div class="dash-layout">
    <div class="dash-sidebar">
      <div class="dash-logo">⚡ Samvad AI</div>
      <div class="dash-nav-item active"><span class="dash-icon">📊</span> Dashboard</div>
      <div class="dash-nav-item" onclick="showSection('chat')"><span class="dash-icon">💬</span> Chat</div>
      <div class="dash-nav-item"><span class="dash-icon">🗂️</span> Conversations</div>
      <div class="dash-nav-item"><span class="dash-icon">👥</span> Leads</div>
      <div class="dash-nav-item"><span class="dash-icon">📈</span> Analytics</div>
      <div class="dash-nav-item"><span class="dash-icon">⚙️</span> Settings</div>
    </div>
    <div class="dash-main">
      <div class="dash-header">
        <div class="dash-welcome"><h2>Welcome back! 👋</h2><p id="dash-date">Loading...</p></div>
        <div class="dash-actions"><div class="notif-btn">🔔<span class="notif-badge">3</span></div><div class="avatar">R</div></div>
      </div>
      <div class="stat-cards">
        <div class="stat-card sc1"><div class="sc-top"><span class="sc-label">Total Chats</span><span class="sc-ico">💬</span></div><div class="sc-val" id="dash-total">0</div><div class="sc-change">↑ Live</div></div>
        <div class="stat-card sc2"><div class="sc-top"><span class="sc-label">AI Resolution</span><span class="sc-ico">✅</span></div><div class="sc-val" id="dash-resolution">89%</div><div class="sc-change">↑ 3% this week</div></div>
        <div class="stat-card sc3"><div class="sc-top"><span class="sc-label">Leads Captured</span><span class="sc-ico">👤</span></div><div class="sc-val" id="dash-leads">342</div><div class="sc-change">↑ 8% this week</div></div>
        <div class="stat-card sc4"><div class="sc-top"><span class="sc-label">Avg Response</span><span class="sc-ico">⚡</span></div><div class="sc-val" id="dash-response">3.2s</div><div class="sc-change">↓ 0.4s faster</div></div>
      </div>
      <div class="dash-grid-2">
        <div class="dash-panel" id="lang-panel"><div class="panel-title">Language Distribution</div></div>
        <div class="dash-panel" id="recent-panel"><div class="panel-title">Recent Conversations</div></div>
      </div>
    </div>
  </div>
  <button class="fab" onclick="showSection('chat')" title="New Chat">💬</button>
</section>

<section id="chat">
  <div class="chat-layout">
    <div class="chat-topbar">
      <div class="mode-selector">
        <button class="mode-btn active" onclick="setMode(this,'support')">🎧 Support</button>
        <button class="mode-btn" onclick="setMode(this,'sales')">💼 Sales</button>
        <button class="mode-btn" onclick="setMode(this,'customer')">🤝 Customer Care</button>
      </div>
      <div class="lang-indicator"><div class="lang-orb"></div><span id="lang-display">Ready...</span></div>
    </div>
    <div class="chat-messages" id="chat-messages">
      <div class="msg ai">
        <div class="msg-avatar">🤖</div>
        <div>
          <div class="msg-bubble">Vanakkam! 🙏 Naan Samvad AI — FlowZint-oda intelligent assistant. Tamil, Hindi, English, Tanglish, Hinglish — ellam pesuvom! Unga business-ku epdi help pannalaam?</div>
          <div class="msg-lang">🇮🇳 Tamil · Hindi · English · Tanglish · Hinglish · +2 more</div>
        </div>
      </div>
    </div>
    <div class="chat-input-area">
      <button class="mic-btn" id="micBtn" title="Click once to start Voice Conversation (Continuous)">🎙️</button>
      <input class="chat-input-box" id="chat-input" type="text" placeholder="Type in Tamil / Hindi / Tanglish / Hinglish..." maxlength="300">
      <button class="send-btn" onclick="sendChatMsg(false)" title="Send (Text Only)">➤</button>
    </div>
  </div>
</section>

<section id="footer-sec">
  <div class="footer-glow-line"></div>
  <div class="footer-body">
    <div class="footer-top">
      <div class="footer-brand"><div class="footer-logo">⚡ Samvad AI</div><p>AI-Powered Business Communication for India. Multi-language, real-time, intelligent conversations at scale.</p><div class="footer-socials"><a class="social-btn">𝕏</a><a class="social-btn">in</a><a class="social-btn">▶</a><a class="social-btn">💬</a></div></div>
      <div class="footer-col"><h4>Product</h4><a href="#">Features</a><a href="#">Pricing</a><a href="#">API Docs</a><a href="#">Changelog</a></div>
      <div class="footer-col"><h4>Company</h4><a href="#">About Us</a><a href="#">Blog</a><a href="#">Careers</a><a href="#">Contact</a></div>
      <div class="footer-col"><h4>Legal</h4><a href="#">Privacy Policy</a><a href="#">Terms of Service</a><a href="#">Security</a><a href="#">Cookie Policy</a></div>
    </div>
    <div class="footer-bottom"><div class="footer-copy">© 2026 Samvad AI. Built for FlowZint AI Hackathon 2026. Made with ❤️ in India 🇮🇳</div><div class="powered-badge">⚡ In partnership with <strong>FlowZint</strong></div></div>
  </div>
</section>
</div>

<script>
// ================== THREE.JS BACKGROUND ==================
const bgCanvas = document.getElementById('bg-canvas');
const renderer = new THREE.WebGLRenderer({canvas:bgCanvas,alpha:true,antialias:true});
renderer.setPixelRatio(Math.min(window.devicePixelRatio,2));
renderer.setSize(window.innerWidth,window.innerHeight);
const bgScene = new THREE.Scene();
const bgCamera = new THREE.PerspectiveCamera(60,window.innerWidth/window.innerHeight,0.1,1000);
bgCamera.position.z = 20;
const particleGeo = new THREE.BufferGeometry();
const pCount = 800;
const pPos = new Float32Array(pCount*3), pCol = new Float32Array(pCount*3);
for(let i=0;i<pCount;i++){ pPos[i*3]=(Math.random()-0.5)*80; pPos[i*3+1]=(Math.random()-0.5)*80; pPos[i*3+2]=(Math.random()-0.5)*40; const t=Math.random(); pCol[i*3]=t<0.5?0.42:0; pCol[i*3+1]=t<0.5?0.23:0.83; pCol[i*3+2]=t<0.5?0.96:1; }
particleGeo.setAttribute('position',new THREE.BufferAttribute(pPos,3));
particleGeo.setAttribute('color',new THREE.BufferAttribute(pCol,3));
const particles = new THREE.Points(particleGeo,new THREE.PointsMaterial({size:0.12,vertexColors:true,transparent:true,opacity:0.7}));
bgScene.add(particles);
const mkWS=(r,x,y,z,c)=>{const m=new THREE.Mesh(new THREE.SphereGeometry(r,12,12),new THREE.MeshBasicMaterial({color:c,wireframe:true,transparent:true,opacity:0.07}));m.position.set(x,y,z);bgScene.add(m);return m;};
const ws1=mkWS(8,-12,5,-10,0x6C3BF5),ws2=mkWS(5,14,-6,-8,0x00D4FF),ws3=mkWS(3,4,-10,-5,0xa78bfa);
let bgT=0;
(function animBg(){requestAnimationFrame(animBg);bgT+=0.003;particles.rotation.y=bgT*0.04;particles.rotation.x=bgT*0.01;ws1.rotation.x=bgT*0.2;ws1.rotation.y=bgT*0.3;ws2.rotation.x=bgT*0.15;ws2.rotation.y=-bgT*0.25;ws3.rotation.z=bgT*0.35;ws1.position.y=5+Math.sin(bgT*0.7)*2;ws2.position.y=-6+Math.cos(bgT*0.5)*2;renderer.render(bgScene,bgCamera);})();

// ================== HERO SPHERE ==================
const hC=document.getElementById('hero-canvas');
const hR=new THREE.WebGLRenderer({canvas:hC,alpha:true,antialias:true});
hR.setPixelRatio(Math.min(window.devicePixelRatio,2)); hR.setSize(420,420);
const hSc=new THREE.Scene(), hCam=new THREE.PerspectiveCamera(50,1,0.1,100);
hCam.position.z=4;
const hSph=new THREE.Mesh(new THREE.SphereGeometry(1.5,64,64),new THREE.MeshPhongMaterial({color:0x0a0820,emissive:0x1a0a40,specular:0x6C3BF5,shininess:120,transparent:true,opacity:0.85}));
hSc.add(hSph);
const hWr=new THREE.Mesh(new THREE.SphereGeometry(1.52,24,24),new THREE.MeshBasicMaterial({color:0x6C3BF5,wireframe:true,transparent:true,opacity:0.18}));
hSc.add(hWr);
const hGl=new THREE.Mesh(new THREE.SphereGeometry(1.2,32,32),new THREE.MeshBasicMaterial({color:0x2a1060,transparent:true,opacity:0.6}));
hSc.add(hGl);
const hRg=new THREE.Mesh(new THREE.TorusGeometry(1.9,0.025,8,100),new THREE.MeshBasicMaterial({color:0x00D4FF,transparent:true,opacity:0.5}));
hRg.rotation.x=Math.PI/3; hSc.add(hRg);
const hRg2=new THREE.Mesh(new THREE.TorusGeometry(2.1,0.015,8,100),new THREE.MeshBasicMaterial({color:0x6C3BF5,transparent:true,opacity:0.3}));
hRg2.rotation.x=Math.PI/2.2; hRg2.rotation.z=Math.PI/4; hSc.add(hRg2);
hSc.add(new THREE.AmbientLight(0x1a0a30,2));
const pLt=new THREE.PointLight(0x6C3BF5,3,8); pLt.position.set(2,2,3); hSc.add(pLt);
const pLt2=new THREE.PointLight(0x00D4FF,2,8); pLt2.position.set(-2,-1,2); hSc.add(pLt2);
let hT=0,mX=0,mY=0;
document.addEventListener('mousemove',e=>{mX=(e.clientX/window.innerWidth-0.5)*0.5;mY=(e.clientY/window.innerHeight-0.5)*0.5;});
(function animH(){requestAnimationFrame(animH);hT+=0.008;hSph.rotation.y=hT*0.4+mX;hSph.rotation.x=mY*0.3;hWr.rotation.y=hT*0.6;hWr.rotation.x=hT*0.2;hRg.rotation.z=hT*0.5;hRg2.rotation.y=-hT*0.3;pLt.position.x=Math.sin(hT)*2.5;pLt.position.y=Math.cos(hT*0.7)*2;pLt2.position.x=Math.cos(hT*0.8)*-2.5;hR.render(hSc,hCam);})();

// ================== APP LOGIC ==================
let chatMode = 'support';
let isTyping = false;
window.convId = null;
let jarvisRecognition = null;
let jarvisActive = false;
let isProcessing = false; // To prevent overlapping requests
let currentTranscript = '';

function showSection(id) {
  document.querySelectorAll('section').forEach(s=>s.style.display='none');
  document.querySelectorAll('.nav-links a').forEach(a=>a.classList.remove('active'));
  const sb = document.getElementById('stats-bar');
  const t = document.getElementById(id);
  if(t){
    if(id==='landing'){t.style.display='flex';sb.style.display='flex';}
    else{t.style.display='block';sb.style.display='none';}
    t.classList.add('section-transition');
    setTimeout(()=>t.classList.remove('section-transition'),500);
  }
  const nav = document.getElementById('nav-'+id);
  if(nav) nav.classList.add('active');
  window.scrollTo(0,0);
  if(id==='dashboard'){loadDashboardStats();loadRecentConversations();}
}
showSection('landing');

const now = new Date();
document.getElementById('dash-date').textContent = now.toLocaleDateString('en-IN',{weekday:'long',year:'numeric',month:'long',day:'numeric'}) + ' · All systems operational';

function setMode(btn, mode) {
  document.querySelectorAll('.mode-btn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  chatMode = mode;
}

function detectLangDisplay(txt) {
  if(/[\u0B80-\u0BFF]/.test(txt)) return 'தமிழ்';
  if(/[\u0900-\u097F]/.test(txt)) return 'हिन्दी';
  const tanglish = ['unga','en','naan','nee','avan','aval','ivanga','ippo','appo','eppadi','sollu','pannu','irukku','vanthu','nalla','romba','konjam','mudiyum','theriyum','padi','velai','veedu','pesu','pesanum','enakku','yennakku','illai','therla','yenakku','yenna','yeppadi','seri','sari','aama','machan','da','bro','anna','akka'];
  const lower = txt.toLowerCase();
  let tc = 0;
  for(const k of tanglish){ if(lower.includes(k)){tc++;if(tc>=2)return 'தமிழ்';} }
  const hinglish = ['aap','tum','mai','hum','kya','kaise','kab','kyu','kaun','hai','hoon','raha','kar','karo','karna','jao','aao','batana','suno','dekho','acha','theek','sahi','nahi','haan','ji','yaar','bhai','bahut','bilkul'];
  let hc = 0;
  for(const k of hinglish){ if(lower.includes(k)){hc++;if(hc>=2)return 'हिन्दी';} }
  return 'English';
}

function getLangCode(ld) {
  if(ld==='தமிழ்') return 'ta';
  if(ld==='हिन्दी') return 'hi';
  return 'en';
}

// ================== TTS FUNCTIONS ===========================
async function speakText(text, langDisplay, callback) {
    if (!text) { if(callback) callback(); return; }
    console.log('🔊 TTS:', text.substring(0, 30), 'Lang:', langDisplay);
    const langCode = getLangCode(langDisplay);
    let ttsFailed = false;

    try {
        const res = await fetch('/api/tts', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, lang: langCode })
        });
        const data = await res.json();
        if (data.audio) {
            const audio = new Audio('data:audio/mp3;base64,' + data.audio);
            audio.onended = () => { if(callback) callback(); };
            audio.onerror = () => { fallbackToBrowserSpeech(text, langDisplay, callback); };
            audio.play().catch(() => { fallbackToBrowserSpeech(text, langDisplay, callback); });
            return;
        } else { ttsFailed = true; }
    } catch (e) { console.log('TTS API Error:', e); ttsFailed = true; }

    if (ttsFailed) { fallbackToBrowserSpeech(text, langDisplay, callback); }
}

function fallbackToBrowserSpeech(text, langDisplay, callback) {
    if (!window.speechSynthesis) { if(callback) callback(); return; }
    window.speechSynthesis.cancel();
    let voices = window.speechSynthesis.getVoices();
    if (voices.length === 0) {
        window.speechSynthesis.onvoiceschanged = () => { 
            voices = window.speechSynthesis.getVoices(); 
            speakWithVoice(text, langDisplay, voices, callback);
        };
    } else { speakWithVoice(text, langDisplay, voices, callback); }
}

function speakWithVoice(text, langDisplay, voices, callback) {
    const lmap = { 'ta': 'ta-IN', 'hi': 'hi-IN', 'en': 'en-US' };
    const targetLang = lmap[getLangCode(langDisplay)] || 'en-US';
    let nativeVoice = null;
    for (const v of voices) { if (v.lang.startsWith(targetLang.split('-')[0])) { nativeVoice = v; break; } }
    if (!nativeVoice && targetLang !== 'en-US') { for (const v of voices) { if (v.lang.startsWith('en')) { nativeVoice = v; break; } } }

    const utterance = new SpeechSynthesisUtterance(text);
    if (nativeVoice) { utterance.voice = nativeVoice; utterance.lang = nativeVoice.lang; } 
    else { utterance.lang = 'en-US'; }
    utterance.rate = 0.9;
    utterance.pitch = 1;
    utterance.onend = () => { if(callback) callback(); };
    utterance.onerror = () => { if(callback) callback(); };
    console.log('🔊 Speaking via browser:', utterance.lang);
    window.speechSynthesis.speak(utterance);
}

// ================== JARVIS HELPERS ==================
function showJarvis(status, sub, listening) {
  document.getElementById('jarvis-overlay').classList.add('active');
  document.getElementById('jarvis-status').textContent = status;
  document.getElementById('jarvis-sub').textContent = sub || 'Tamil · Hindi · English supported';
  document.getElementById('jarvis-core-icon').textContent = listening ? '🎙️' : '🤖';
  document.querySelectorAll('.jarvis-bar').forEach(b => b.classList.toggle('idle', !listening));
}

function hideJarvis() {
  document.getElementById('jarvis-overlay').classList.remove('active');
  document.getElementById('micBtn').classList.remove('jarvis-active');
  jarvisActive = false;
  if(jarvisRecognition) { try{ jarvisRecognition.stop(); } catch(e){} }
}

function cancelJarvis() {
  isProcessing = false;
  currentTranscript = '';
  if(jarvisRecognition) { try{ jarvisRecognition.stop(); } catch(e){} }
  hideJarvis();
}

// ================== CONTINUOUS CONVERSATION LOGIC ==================

// Function to restart listening
function startListening() {
    if (!jarvisActive) return;
    if (isProcessing) {
        console.log('Waiting for processing to finish...');
        return;
    }
    // If recognition already exists, stop and restart
    if (jarvisRecognition) {
        try { jarvisRecognition.stop(); } catch(e) {}
        jarvisRecognition = null;
    }
    
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { alert('Speech recognition not supported.'); return; }
    
    const recognition = new SR();
    jarvisRecognition = recognition;
    recognition.lang = 'en-US';
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;

    let finalText = '';
    let interimText = '';
    let silenceTimer = null;

    recognition.onstart = () => {
        console.log('🎧 Listening...');
        showJarvis('Listening...', 'Speak now...', true);
        finalText = '';
        interimText = '';
        document.getElementById('jarvis-send-btn').style.display = 'inline-block';
        document.getElementById('jarvis-send-btn').onclick = function() {
            if (silenceTimer) clearTimeout(silenceTimer);
            if (finalText.trim() || interimText.trim()) {
                processVoiceInput(finalText + interimText);
            }
        };
    };

    recognition.onresult = (event) => {
        if (silenceTimer) clearTimeout(silenceTimer);
        let interim = '';
        for (let i = event.resultIndex; i < event.results.length; i++) {
            if (event.results[i].isFinal) { finalText += event.results[i][0].transcript; } 
            else { interim += event.results[i][0].transcript; }
        }
        interimText = interim;
        const display = finalText + interim;
        if (display) {
            const lang = detectLangDisplay(display);
            document.getElementById('jarvis-status').textContent = display.length > 40 ? display.substring(0,40)+'...' : display;
            document.getElementById('jarvis-sub').textContent = 'Language: ' + lang + ' (click Send or wait)';
        }
        // Auto-send after 3 seconds of silence
        silenceTimer = setTimeout(() => {
            if (finalText.trim() || interimText.trim()) {
                processVoiceInput(finalText + interimText);
            }
        }, 3000);
    };

    recognition.onerror = (event) => {
        console.warn('Mic Error:', event.error);
        if (event.error === 'no-speech' || event.error === 'aborted') {
            // Silently ignore, maybe restart if still active
        } else if (event.error === 'not-allowed') {
            alert('Please allow microphone access.');
            cancelJarvis();
        } else {
            // Try to restart
            if (jarvisActive && !isProcessing) {
                setTimeout(() => startListening(), 500);
            }
        }
    };

    recognition.onend = () => {
        console.log('🔇 Recognition ended.');
        // If still active and not processing, restart automatically
        if (jarvisActive && !isProcessing) {
            // Check if we have pending text
            if (finalText.trim() || interimText.trim()) {
                processVoiceInput(finalText + interimText);
            } else {
                // Restart listening
                setTimeout(() => startListening(), 300);
            }
        }
    };

    recognition.start();
}

// Process voice input -> Send to AI -> Speak reply -> Continue loop
function processVoiceInput(text) {
    if (!text.trim()) return;
    if (isProcessing) return;
    isProcessing = true;
    
    // Stop recognition temporarily
    if (jarvisRecognition) {
        try { jarvisRecognition.stop(); } catch(e) {}
    }
    
    // Clear the overlay status
    showJarvis('Processing...', 'AI is thinking...', false);
    document.getElementById('jarvis-send-btn').style.display = 'none';
    
    // Set the text in the chat input and send
    document.getElementById('chat-input').value = text.trim();
    
    // Call sendChatMsg with speak mode enabled
    sendChatMsg(true).then(() => {
        // Wait a bit and then restart listening
        isProcessing = false;
        if (jarvisActive) {
            setTimeout(() => startListening(), 1500);
        }
    }).catch(() => {
        isProcessing = false;
        if (jarvisActive) {
            setTimeout(() => startListening(), 1500);
        }
    });
}

// ================== JARVIS MIC START ==================
document.getElementById('micBtn').addEventListener('click', function() {
  if(jarvisActive){ cancelJarvis(); return; }
  
  if(!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)){
    alert('Voice input requires Chrome browser.');
    return;
  }

  jarvisActive = true;
  isProcessing = false;
  this.classList.add('jarvis-active');
  
  // Show overlay with greeting
  showJarvis('Initializing Samvad AI...', 'Starting up...', false);
  
  // Greet and then start listening
  const greetings = [
    { lang:'தமிழ்', text:'Vanakkam! Naan Samvad AI. Enna help pannalaam?', code:'ta' },
    { lang:'हिन्दी', text:'Namaste! Main Samvad AI hoon. Kaise help karoon?', code:'hi' },
    { lang:'English', text:'Hello! I am Samvad AI. How can I help you today?', code:'en' }
  ];
  const g = greetings[Math.floor(Math.random() * greetings.length)];
  
  showJarvis('Hello! Pesungal...', g.lang + ' detected', true);
  
  speakText(g.text, g.lang, () => {
      // After greeting, start listening
      if (jarvisActive) {
          startListening();
      }
  });
});

// ================== SEND CHAT ==================
async function sendChatMsg(shouldSpeak = false) {
  if(isTyping) return;
  const inp = document.getElementById('chat-input');
  const txt = inp.value.trim();
  if(!txt) return;
  inp.value = '';

  const ld = detectLangDisplay(txt);
  document.getElementById('lang-display').textContent = 'Detected: ' + ld;

  const msgs = document.getElementById('chat-messages');
  msgs.innerHTML += `<div class="msg user"><div class="msg-avatar">👤</div><div><div class="msg-bubble">${txt}</div><div class="msg-lang">${ld}</div></div></div>`;

  const tid = 'typing-'+Date.now();
  msgs.innerHTML += `<div class="msg ai" id="${tid}"><div class="msg-avatar">🤖</div><div class="typing-bubble"><div class="t-dot"></div><div class="t-dot"></div><div class="t-dot"></div></div></div>`;
  msgs.scrollTop = msgs.scrollHeight;
  isTyping = true;

  try {
    const res = await fetch('/api/chat-stream',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({message:txt,mode:chatMode,conversation_id:window.convId||null})
    });
    if(!res.ok) throw new Error('Server error');

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let aiReply = '';

    document.getElementById(tid)?.remove();
    const mid = 'ai-msg-'+Date.now();
    msgs.innerHTML += `<div class="msg ai" id="${mid}"><div class="msg-avatar">🤖</div><div><div class="msg-bubble" id="bubble-${mid}"></div><div class="msg-lang">🤖 Samvad AI · ${chatMode} · ${ld}</div></div></div>`;
    const bubble = document.getElementById('bubble-'+mid);

    while(true){
      const {done,value} = await reader.read();
      if(done) break;
      const lines = decoder.decode(value).split('\n');
      for(const line of lines){
        if(line.startsWith('data: ')){
          const c = line.substring(6);
          if(c==='[DONE]') break;
          aiReply += c;
          if(bubble) bubble.textContent = aiReply;
          msgs.scrollTop = msgs.scrollHeight;
        }
      }
    }
    
    // Speak only if shouldSpeak is true
    if (shouldSpeak === true) {
        console.log('🔊 Speaking Reply...');
        await new Promise((resolve) => {
            speakText(aiReply, ld, resolve);
        });
    }
    
    return aiReply; // Return for the voice loop
    
  } catch(err) {
    console.error('Chat error:',err);
    document.getElementById(tid)?.remove();
    msgs.innerHTML += `<div class="msg ai"><div class="msg-avatar">🤖</div><div><div class="msg-bubble">⚠️ Server error — please try again! 🔄</div></div></div>`;
    throw err;
  } finally {
    msgs.scrollTop = msgs.scrollHeight;
    isTyping = false;
  }
}

// ================== ENTER KEY (Text Only) ==================
document.getElementById('chat-input').addEventListener('keydown', function(e) { 
    if(e.key === 'Enter') { 
        e.preventDefault(); 
        sendChatMsg(false); 
    } 
});

// ================== DASHBOARD ==================
async function loadDashboardStats() {
  try {
    const res = await fetch('/api/stats');
    const data = await res.json();
    document.getElementById('dash-total').textContent = data.total_conversations||0;
    document.getElementById('stat-convos').textContent = (data.total_conversations||0)+'';
    const lp = document.getElementById('lang-panel');
    const langs = data.languages||{};
    let html = `<div class="panel-title">Language Distribution</div>`;
    const colors=['lb1','lb2','lb3','lb4','lb5'];
    let i=0, total=data.total_conversations||1;
    for(const [name,count] of Object.entries(langs)){
      const pct=Math.round((count/total)*100);
      html+=`<div class="lang-row"><div class="lang-info"><span class="lang-name">${name}</span><span class="lang-pct">${pct}%</span></div><div class="lang-bar-bg"><div class="lang-bar ${colors[i%5]}" style="width:${pct}%"></div></div></div>`;
      i++;
    }
    if(i===0) html+=`<p style="color:rgba(255,255,255,0.4)">No conversations yet.</p>`;
    lp.innerHTML=html;
  } catch(e){console.log('Stats error:',e);}
}

async function loadRecentConversations() {
  try {
    const res = await fetch('/api/history');
    const convos = await res.json();
    const panel = document.getElementById('recent-panel');
    let html = `<div class="panel-title">Recent Conversations</div>`;
    const recent = convos.slice(-4).reverse();
    if(!recent.length){html+=`<p style="color:rgba(255,255,255,0.4)">No conversations yet. Start chatting!</p>`;}
    else{
      const colors=['ca1','ca2','ca3','ca4'];
      const badges={'Tamil':'cb-ta','Hindi':'cb-hi','English':'cb-en','Malayalam':'cb-ml'};
      recent.forEach((c,idx)=>{
        const color=colors[idx%4], badge=badges[c.language]||'cb-en', init=c.language?c.language[0]:'U';
        html+=`<div class="conv-item"><div class="conv-avatar ${color}">${init}</div><div class="conv-info"><div class="conv-name">${c.id}</div><div class="conv-preview">${c.count} messages</div></div><span class="conv-badge ${badge}">${c.language}</span></div>`;
      });
    }
    panel.innerHTML=html;
  } catch(e){console.log('History error:',e);}
}

window.addEventListener('resize',()=>{
  renderer.setSize(window.innerWidth,window.innerHeight);
  bgCamera.aspect=window.innerWidth/window.innerHeight;
  bgCamera.updateProjectionMatrix();
});
</script>
</body>
</html>
"""

# ============================================================
# BACKEND ROUTES
# ============================================================
@app.route('/')
def index():
    return render_template_string(UI_HTML)

@app.route('/api/tts', methods=['POST'])
def text_to_speech():
    data = request.json
    text = data.get('text','').strip()
    lang_code = data.get('lang','en')
    if not text: return jsonify({'audio':None,'error':'No text'})
    if not GTTS_AVAILABLE: return jsonify({'audio':None,'error':'gTTS not installed'})
    try:
        tts = gTTS(text=text, lang=lang_code, slow=False)
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        buf.seek(0)
        audio_b64 = base64.b64encode(buf.read()).decode('utf-8')
        print(f"✅ gTTS Success: lang={lang_code}, chars={len(text)}")
        return jsonify({'audio': audio_b64})
    except Exception as e:
        print(f"❌ gTTS Error: {e}")
        return jsonify({'audio':None,'error':str(e)})

@app.route('/api/chat-stream', methods=['POST'])
def chat_stream():
    global cnt
    data = request.json
    msg = data.get('message','').strip()
    cid = data.get('conversation_id','')
    mode = data.get('mode','support')
    if not msg: return jsonify({'error':'Message required'}),400

    lang = detect_language(msg)
    if not cid or cid not in convos:
        cnt += 1
        cid = f"c{cnt}"
        convos[cid] = {'id':cid,'messages':[],'language':lang,'mode':mode}
    convos[cid]['messages'].append({'role':'user','content':msg,'language':lang})

    lang_instruction = {
        "Tamil": "MANDATORY: Reply in Tamil/Tanglish. Mix Tamil words naturally.",
        "Hindi": "MANDATORY: Reply in Hindi/Hinglish. Mix Hindi words naturally.",
        "English": "Reply in clear, friendly English."
    }

    system_prompt = (
        f"You are Samvad AI - FlowZint's intelligent business assistant.\n"
        f"Current Mode: {mode.upper()}\n\n"
        f"{MODE_PROMPTS.get(mode, MODE_PROMPTS['support'])}\n\n"
        f"USER'S LANGUAGE: {lang}\n"
        f"{lang_instruction.get(lang, lang_instruction['English'])}\n\n"
        f"RULES:\n"
        f"1. NEVER switch language\n"
        f"2. Keep replies SHORT: 2-3 sentences max\n"
        f"3. Be warm and conversational, not robotic"
    )

    def generate():
        if not client:
            yield "data: ⚠️ Set GROQ_API_KEY in Render Env Vars.\n\n"
            yield "data: [DONE]\n\n"
            return
        try:
            messages = [{"role":"system","content":system_prompt}]
            for m in convos[cid]['messages'][-10:]:
                messages.append({"role":m['role'],"content":m['content']})
            stream = client.chat.completions.create(
                model=MODEL, messages=messages, temperature=0.75,
                max_tokens=500, stream=True
            )
            full_reply = ""
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    full_reply += content
                    yield f"data: {content}\n\n"
            convos[cid]['messages'].append({'role':'assistant','content':full_reply,'language':lang})
        except Exception as e:
            yield f"data: ⚠️ Error: {str(e)[:100]}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream")

@app.route('/api/voice/token', methods=['POST'])
def voice_token():
    data = request.json or {}
    channel = data.get('channel', f'samvad_{uuid.uuid4().hex[:8]}')
    uid = data.get('uid', 0)
    token_data = gen_agora_token(channel, uid)
    call_id = f"call_{uuid.uuid4().hex[:12]}"
    calls[call_id] = {"id":call_id,"channel":channel,"started_at":datetime.now().isoformat(),"status":"connected"}
    return jsonify({"call_id":call_id,"token":token_data["token"],"app_id":token_data["app_id"],"channel":channel,"uid":uid,"simulated":token_data["simulated"]})

@app.route('/api/voice/process', methods=['POST'])
def voice_process():
    data = request.json or {}
    text = data.get('text','').strip()
    if not text: return jsonify({'reply':'','error':'No text'}),400
    lang = detect_language(text)
    prompt = f"You are Samvad AI CALL CENTER. Reply in {lang} (2 sentences max, warm tone).\nCustomer: {text}"
    try:
        if not client: reply="AI unavailable."
        else:
            r=client.chat.completions.create(model=MODEL,messages=[{"role":"system","content":prompt}],temperature=0.7,max_tokens=150)
            reply=r.choices[0].message.content
        return jsonify({'reply':reply,'language':lang})
    except Exception as e:
        return jsonify({'reply':f"Error: {str(e)}",'language':lang}),500

@app.route('/api/voice/end', methods=['POST'])
def voice_end():
    return jsonify({'status':'ended','message':'Call ended.'})

@app.route('/api/stats')
def stats():
    total = len(convos)
    lang_count = {}
    for c in convos.values():
        l = c.get('language','English')
        lang_count[l] = lang_count.get(l,0)+1
    return jsonify({'total_conversations':total,'languages':lang_count})

@app.route('/api/history')
def history():
    return jsonify([{'id':c['id'],'language':c.get('language','English'),'mode':c.get('mode','support'),'count':len(c['messages'])} for c in convos.values()])

@app.route('/api/flowzint/create-lead', methods=['POST'])
def create_lead():
    data = request.json or {}
    pid = f"FLWZ-{uuid.uuid4().hex[:8].upper()}"
    return jsonify({'success':True,'message':'✅ Lead converted to FlowZint Project!','project_id':pid,'workspace_url':f'https://flowzint.in/workspace/{pid}'})

@app.route('/api/health')
def health():
    return jsonify({
        'status':'ok',
        'groq':'Connected' if client else 'Missing GROQ_API_KEY',
        'gtts':'Installed' if GTTS_AVAILABLE else 'Run: pip install gTTS',
        'agora':'Configured' if (AGORA_APP_ID and AGORA_APP_ID!='demo') else 'Simulated mode',
        'version':'15.0 - CONTINUOUS CONVERSATION'
    })

if __name__ == '__main__':
    port = int(os.getenv("PORT",5000))
    print("\n" + "="*70)
    print("  SAMVAD AI v15.0 - CONTINUOUS CONVERSATION")
    print("="*70)
    print(f"  Server   : http://localhost:{port}")
    print(f"  Groq AI  : {'READY' if client else 'Set GROQ_API_KEY'}")
    print(f"  gTTS     : {'INSTALLED' if GTTS_AVAILABLE else 'Run: pip install gTTS'}")
    print("="*70)
    print("  ✅ CHAT (Type + Enter)  -> Text only, NO voice")
    print("  ✅ MIC (Click once)     -> Continuous Voice Conversation")
    print("  ✅ AI listens -> Speaks -> Listens again (Auto-loop)")
    print("  ✅ Click 'End Conversation' to stop")
    print("="*70+"\n")
    app.run(debug=False, host='0.0.0.0', port=port)