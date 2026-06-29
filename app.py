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

# ====================== ENHANCED LANGUAGE DETECTION ======================
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
    'vanakkam','namasthe','superam','machan','da','di','bro','akka','anna',
    'romba','konjam','mikka','neraiya','nalla','kettadhu','seri','sari','aama',
    'theriyala','therinjukku','mudiyala','mudiyum','vendam','venum','pothum',
    'oru','rendu','moondru','naalu','aindhu','aaru','ezhu','ettu','ombathu','pathu',
    'paisa','kasu','panam','padippu','padi','school','college','padippa',
    'unga','en','naan','nee','avan','aval','ivanga','avanga','eppadi','ippo','appo',
    'sollu','pannu','irukku','vanthu','pesu','pesanum','theriyum','enakku','yennakku',
    'illai','therla','puriyala','puriyuthu','veetla','kadai','office','shop',
    'machan','bro','akka','anna','da','di','yaaru'
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
    'namaste','namaskar','kaam','paisa','help','karo','bolo',
    'hai','hain','hoon','the','thi','raha','rahi','rahe',
    'kar','karo','karna','karte','karta','karti','karega',
    'jao','jaana','jaate','jaega','aao','aana','aate','aega',
    'batana','batavo','batao','bataiye','sunna','suno','suniye',
    'dekho','dekha','dekhna','acha','theek','sahi','galat','nahi',
    'haan','ji','bhai','behan','mera','tera','uska','humara',
    'tumhara','apna','chahiye','chahie','manga','mangta','dena',
    'do','dunga','abhi','kal','aaj','subah','shaam','raat','din'
}

# Common English words to detect English
ENGLISH_COMMON = {
    'hello','hi','hey','yes','no','ok','okay','thanks','thank','please','help','sorry',
    'good','bad','fine','well','great','awesome','cool','nice','love','like','want',
    'need','get','have','do','go','come','see','look','tell','say','ask','answer',
    'know','think','feel','work','time','day','week','month','year','today','tomorrow',
    'yesterday','now','later','soon','always','never','maybe','probably','actually',
    'really','very','too','also','just','only','even','still','already','yet','ever',
    'once','twice','three','four','five','six','seven','eight','nine','ten'
}

def detect_language(text):
    if not text or not text.strip():
        return "English"
    
    text_lower = text.lower()
    
    # 1. Script detection (highest priority)
    tamil_script_count = sum(1 for c in text if c in TAMIL_SCRIPT)
    hindi_script_count = sum(1 for c in text if c in HINDI_SCRIPT)
    if tamil_script_count >= 2:
        return "Tamil"
    if hindi_script_count >= 2:
        return "Hindi"
    
    # 2. Tokenize
    text_clean = re.sub(r'[^a-z0-9 ]', ' ', text_lower)
    words = set(text_clean.split())
    
    # 3. Count matches for each language
    tamil_matches = 0
    hindi_matches = 0
    english_matches = 0
    
    for w in words:
        if w in TAMIL_KEYWORDS:
            tamil_matches += 1
        if w in HINDI_KEYWORDS:
            hindi_matches += 1
        if w in ENGLISH_COMMON:
            english_matches += 1
    
    # 4. Substring matches for longer words
    if tamil_matches < 3:
        for key in TAMIL_KEYWORDS:
            if len(key) > 3 and key in text_lower:
                tamil_matches += 0.5
    if hindi_matches < 3:
        for key in HINDI_KEYWORDS:
            if len(key) > 3 and key in text_lower:
                hindi_matches += 0.5
    
    # 5. Decision logic
    # If Hindi score is significantly higher than Tamil and >=2
    if hindi_matches > tamil_matches and hindi_matches >= 2:
        return "Hindi"
    if tamil_matches > hindi_matches and tamil_matches >= 2:
        return "Tamil"
    
    # If both scores are low but English words present
    if english_matches >= 2:
        return "English"
    
    # Fallback to whichever has at least 2 matches
    if tamil_matches >= 2:
        return "Tamil"
    if hindi_matches >= 2:
        return "Hindi"
    
    return "English"

MODE_PROMPTS = {
    "sales": """You are a FRIENDLY Sales Agent at FlowZint. Always capture lead details. Keep replies SHORT: 2-3 sentences.""",
    "support": """You are a PATIENT Technical Support Agent at FlowZint. Ask clear questions. Give step-by-step solutions. Keep replies CONCISE: 3-4 sentences.""",
    "customer": """You are an EMPATHETIC Customer Care Agent at FlowZint. Always apologize first. Offer solutions. Short, human replies: 2-3 sentences."""
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
# UI HTML – WITH CORRECT LANGUAGE DETECTION
# ============================================================
UI_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>Samvad AI — Multilingual Voice AI</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:ital,wght@0,300;0,400;0,500;0,600;1,400&display=swap" rel="stylesheet">
<style>
/* ===== CSS RESET & ROOT TOKENS ===== */
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth;font-size:16px}

:root {
  /* Warm Ivory Palette */
  --bg:       #F4EBDD;
  --bg2:      #ECE1CF;
  --bg3:      #F7F1E8;
  --border:   #DDD2C0;

  /* Forest Green Primary */
  --green:    #254F2D;
  --green-dk: #1E4126;
  --sage:     #7A8D5C;
  --sage-lt:  #A9B28D;
  --olive:    #69784D;

  /* Gold Accent */
  --gold:     #C7A86B;
  --gold-lt:  #E4D2AA;

  /* Typography */
  --text:     #263124;
  --text2:    #5B6851;
  --text3:    #8A927F;
  --textd:    #B8B3A8;

  /* Status */
  --success:  #4D7C3A;
  --warn:     #C79B32;
  --error:    #A94A3F;
  --info:     #5D7A66;

  /* Neumorphism shadows - the core system */
  --neu-light: #FFFFFF;
  --neu-dark:  #D3C6B3;
  --neu-out:   6px 6px 14px #D3C6B3, -4px -4px 10px #FFFFFF;
  --neu-in:    inset 4px 4px 10px #D3C6B3, inset -3px -3px 8px #FFFFFF;
  --neu-out-sm:3px 3px 8px #D3C6B3, -2px -2px 6px #FFFFFF;
  --neu-press: inset 3px 3px 8px #C4B89E, inset -2px -2px 6px #FFFFFF;
  --neu-gold:  4px 4px 12px #C4A466, -2px -2px 8px #FFFFFF;
  --neu-green: 4px 4px 14px rgba(37,79,45,0.25), -2px -2px 8px #FFFFFF;

  /* Font families */
  --font-display: 'DM Serif Display', serif;
  --font-body: 'DM Sans', sans-serif;

  /* Transitions */
  --trans: all 0.28s cubic-bezier(0.23,1,0.32,1);
  --trans-fast: all 0.16s ease;
}

body {
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-body);
  font-weight: 400;
  line-height: 1.6;
  overflow-x: hidden;
  -webkit-font-smoothing: antialiased;
}

/* ===== AMBIENT BACKGROUND ===== */
.ambient {
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  overflow: hidden;
}
.amb-blob {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.18;
  animation: blobDrift 18s ease-in-out infinite alternate;
}
.amb-blob:nth-child(1){width:500px;height:500px;background:#7A8D5C;top:-100px;left:-100px;animation-duration:22s}
.amb-blob:nth-child(2){width:400px;height:400px;background:#C7A86B;top:40%;right:-120px;animation-duration:17s;animation-delay:-5s}
.amb-blob:nth-child(3){width:300px;height:300px;background:#254F2D;bottom:-80px;left:30%;animation-duration:25s;animation-delay:-10s}
@keyframes blobDrift{0%{transform:translate(0,0) scale(1)}100%{transform:translate(40px,30px) scale(1.08)}}

/* ===== NAV ===== */
nav {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 48px;
  height: 70px;
  background: rgba(244,235,221,0.82);
  backdrop-filter: blur(24px);
  -webkit-backdrop-filter: blur(24px);
  border-bottom: 1px solid rgba(221,210,192,0.6);
}
.nav-logo {
  display: flex;
  align-items: center;
  gap: 10px;
  font-family: var(--font-display);
  font-size: 22px;
  color: var(--green);
  text-decoration: none;
  cursor: pointer;
}
.logo-orb {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: var(--bg);
  box-shadow: var(--neu-out-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  transition: var(--trans);
}
.nav-logo:hover .logo-orb{box-shadow:var(--neu-press)}
.nav-links {
  display: flex;
  align-items: center;
  gap: 4px;
}
.nav-link {
  padding: 8px 18px;
  border-radius: 20px;
  font-size: 14px;
  font-weight: 500;
  color: var(--text2);
  cursor: pointer;
  border: none;
  background: transparent;
  font-family: var(--font-body);
  transition: var(--trans-fast);
  text-decoration: none;
}
.nav-link:hover{color:var(--green)}
.nav-link.active{color:var(--green);background:var(--bg);box-shadow:var(--neu-out-sm)}
.nav-cta {
  padding: 10px 24px;
  border-radius: 24px;
  font-size: 14px;
  font-weight: 600;
  color: var(--neu-light);
  background: var(--green);
  border: none;
  cursor: pointer;
  font-family: var(--font-body);
  transition: var(--trans);
  box-shadow: var(--neu-green);
  letter-spacing: 0.01em;
}
.nav-cta:hover{background:var(--green-dk);transform:translateY(-1px);box-shadow:5px 5px 16px rgba(37,79,45,0.35),-2px -2px 8px #FFFFFF}

/* ===== PAGE SHELL ===== */
.page{position:relative;z-index:1}
section{display:none;min-height:100vh;padding:90px 48px 80px;animation:secFade 0.5s ease}
section.active{display:block}
@keyframes secFade{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:translateY(0)}}

/* ===== SECTION: LANDING ===== */
#landing {
  display: none;
  flex-direction: column;
  align-items: center;
  padding-top: 120px;
}
#landing.active{display:flex}

.hero-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: var(--bg);
  box-shadow: var(--neu-out-sm);
  border-radius: 20px;
  padding: 7px 18px 7px 12px;
  font-size: 13px;
  font-weight: 500;
  color: var(--green);
  margin-bottom: 32px;
}
.badge-dot{
  width:8px;height:8px;border-radius:50%;
  background:var(--gold);
  box-shadow:0 0 0 3px rgba(199,168,107,0.25);
  animation:badgePop 2.4s ease-in-out infinite;
}
@keyframes badgePop{0%,100%{box-shadow:0 0 0 2px rgba(199,168,107,0.2)}50%{box-shadow:0 0 0 6px rgba(199,168,107,0)}}

.hero-headline {
  font-family: var(--font-display);
  font-size: clamp(52px, 8vw, 96px);
  line-height: 1.02;
  letter-spacing: -2px;
  color: var(--text);
  text-align: center;
  margin-bottom: 24px;
  max-width: 880px;
}
.hero-headline em{font-style:italic;color:var(--green)}
.hero-headline .accent-word{
  position:relative;
  display:inline-block;
  color:var(--green);
}
.hero-headline .accent-word::after{
  content:'';
  position:absolute;
  bottom:-4px;left:0;right:0;
  height:4px;
  background:linear-gradient(90deg,var(--gold),var(--sage));
  border-radius:2px;
}

.hero-sub {
  font-size: 18px;
  color: var(--text2);
  text-align: center;
  max-width: 540px;
  line-height: 1.75;
  margin-bottom: 44px;
}

.hero-btns{display:flex;gap:16px;flex-wrap:wrap;justify-content:center;margin-bottom:72px}

.btn-neu {
  padding: 14px 36px;
  border-radius: 28px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  border: none;
  font-family: var(--font-body);
  transition: var(--trans);
  background: var(--bg);
  color: var(--green);
  box-shadow: var(--neu-out);
  letter-spacing: 0.01em;
}
.btn-neu:hover{box-shadow:var(--neu-press);transform:translateY(1px)}
.btn-neu:active{box-shadow:var(--neu-in);transform:translateY(2px)}
.btn-primary-solid {
  background: var(--green);
  color: #fff;
  box-shadow: var(--neu-green);
}
.btn-primary-solid:hover{background:var(--green-dk);transform:translateY(-2px);box-shadow:6px 6px 16px rgba(37,79,45,0.35),-2px -2px 8px #FFFFFF}
.btn-primary-solid:active{transform:translateY(0);box-shadow:var(--neu-press)}

/* ===== HERO VISUAL ===== */
.hero-visual {
  position: relative;
  width: 340px;
  height: 340px;
  margin: 0 auto 72px;
}
.hero-orb {
  width: 340px;
  height: 340px;
  border-radius: 50%;
  background: var(--bg);
  box-shadow: 12px 12px 30px var(--neu-dark), -8px -8px 20px var(--neu-light);
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  animation: orbFloat 5s ease-in-out infinite;
}
@keyframes orbFloat{0%,100%{transform:translateY(0)}50%{transform:translateY(-12px)}}
.orb-inner {
  width: 220px;
  height: 220px;
  border-radius: 50%;
  background: var(--bg3);
  box-shadow: inset 6px 6px 16px var(--neu-dark), inset -4px -4px 12px var(--neu-light);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 6px;
}
.orb-text {
  font-family: var(--font-display);
  font-size: 28px;
  color: var(--green);
  letter-spacing: -0.5px;
}
.orb-sub{font-size:12px;color:var(--text3);letter-spacing:0.05em}

/* Orbit chips */
.orbit-chip {
  position: absolute;
  background: var(--bg);
  border-radius: 20px;
  padding: 8px 14px;
  font-size: 12px;
  font-weight: 600;
  color: var(--green);
  box-shadow: var(--neu-out-sm);
  white-space: nowrap;
  animation: chipDrift 6s ease-in-out infinite alternate;
}
.chip1{top:0;left:50%;transform:translateX(-50%);animation-delay:0s}
.chip2{top:50%;left:-20px;transform:translateY(-50%);animation-delay:-2s}
.chip3{bottom:20px;right:-10px;animation-delay:-4s}
.chip4{bottom:0;left:50%;transform:translateX(-50%);animation-delay:-1s}
@keyframes chipDrift{0%{transform:translateY(0) translateX(0)}100%{transform:translateY(-8px) translateX(4px)}}
.chip1{animation:c1float 5s ease-in-out infinite}
.chip2{animation:c2float 6s ease-in-out infinite}
.chip3{animation:c3float 4.5s ease-in-out infinite}
.chip4{animation:c4float 7s ease-in-out infinite}
@keyframes c1float{0%,100%{top:0px}50%{top:-10px}}
@keyframes c2float{0%,100%{left:-20px}50%{left:-30px}}
@keyframes c3float{0%,100%{bottom:20px}50%{bottom:12px}}
@keyframes c4float{0%,100%{bottom:0px}50%{bottom:-10px}}

/* ===== STATS BAR ===== */
.stats-bar {
  display: flex;
  justify-content: center;
  gap: 0;
  max-width: 800px;
  width: 100%;
  margin: 0 auto;
  background: var(--bg);
  border-radius: 28px;
  box-shadow: var(--neu-out);
  overflow: hidden;
}
.stat-item {
  flex: 1;
  text-align: center;
  padding: 28px 20px;
  border-right: 1px solid var(--border);
  transition: var(--trans);
}
.stat-item:last-child{border-right:none}
.stat-item:hover{background:var(--bg3)}
.stat-num {
  font-family: var(--font-display);
  font-size: 36px;
  color: var(--green);
  display: block;
  line-height: 1;
  margin-bottom: 6px;
}
.stat-label{font-size:12px;color:var(--text3);letter-spacing:0.05em;text-transform:uppercase;font-weight:500}

/* ===== SECTION: FEATURES ===== */
#features{display:none}
#features.active{display:block}
.sec-header{text-align:center;margin-bottom:64px}
.sec-eyebrow {
  display: inline-block;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--gold);
  margin-bottom: 16px;
  padding: 6px 16px;
  border-radius: 12px;
  background: var(--bg);
  box-shadow: var(--neu-out-sm);
}
.sec-title {
  font-family: var(--font-display);
  font-size: clamp(36px, 5vw, 56px);
  color: var(--text);
  letter-spacing: -1px;
  line-height: 1.08;
  margin-bottom: 14px;
}
.sec-title span{color:var(--green)}
.sec-sub{font-size:17px;color:var(--text2);max-width:480px;margin:0 auto;line-height:1.7}

.feat-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 28px;
  max-width: 960px;
  margin: 0 auto;
}

.feat-card {
  background: var(--bg);
  border-radius: 28px;
  padding: 40px 36px;
  box-shadow: var(--neu-out);
  position: relative;
  overflow: hidden;
  cursor: default;
  transition: var(--trans);
}
.feat-card::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: 28px;
  background: linear-gradient(135deg, rgba(122,141,92,0.06), rgba(199,168,107,0.04));
  opacity: 0;
  transition: opacity 0.4s;
}
.feat-card:hover{box-shadow:8px 8px 20px var(--neu-dark),-4px -4px 12px var(--neu-light);transform:translateY(-4px)}
.feat-card:hover::before{opacity:1}

.feat-icon {
  width: 64px;
  height: 64px;
  border-radius: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 28px;
  margin-bottom: 22px;
  box-shadow: var(--neu-out-sm);
  background: var(--bg);
  transition: var(--trans);
}
.feat-card:hover .feat-icon{box-shadow:var(--neu-press)}
.feat-card h3 {
  font-family: var(--font-display);
  font-size: 22px;
  color: var(--text);
  margin-bottom: 10px;
  letter-spacing: -0.3px;
}
.feat-card p{font-size:15px;color:var(--text2);line-height:1.7}
.feat-tag {
  display: inline-block;
  margin-top: 20px;
  padding: 5px 14px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
  background: var(--bg3);
  color: var(--olive);
  box-shadow: var(--neu-out-sm);
  letter-spacing: 0.03em;
}

/* ===== SECTION: DASHBOARD ===== */
#dashboard{display:none;padding:0}
#dashboard.active{display:block}
.dash-layout {
  height: 100vh;
  display: flex;
  padding-top: 70px;
}

.dash-sidebar {
  width: 220px;
  background: var(--bg2);
  border-right: 1px solid var(--border);
  padding: 28px 0;
  flex-shrink: 0;
  box-shadow: 4px 0 12px rgba(211,198,179,0.3);
}
.dash-logo {
  padding: 0 22px 24px;
  font-family: var(--font-display);
  font-size: 19px;
  color: var(--green);
  border-bottom: 1px solid var(--border);
  margin-bottom: 20px;
}
.dash-nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 22px;
  font-size: 14px;
  font-weight: 500;
  color: var(--text2);
  cursor: pointer;
  transition: var(--trans-fast);
  border-left: 3px solid transparent;
  border-radius: 0 16px 16px 0;
  margin: 1px 12px 1px 0;
}
.dash-nav-item:hover{color:var(--green);background:rgba(37,79,45,0.06)}
.dash-nav-item.active{color:var(--green);border-left-color:var(--green);background:var(--bg);box-shadow:var(--neu-out-sm)}
.dash-icon{font-size:16px}

.dash-main {
  flex: 1;
  padding: 28px 32px;
  overflow-y: auto;
  background: var(--bg);
}
.dash-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 28px;
}
.dash-welcome h2 {
  font-family: var(--font-display);
  font-size: 24px;
  color: var(--text);
}
.dash-welcome p{font-size:13px;color:var(--text3);margin-top:3px}
.dash-actions{display:flex;align-items:center;gap:14px}
.notif-btn {
  position: relative;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: var(--bg);
  box-shadow: var(--neu-out-sm);
  border: none;
  cursor: pointer;
  font-size: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: var(--trans);
}
.notif-btn:hover{box-shadow:var(--neu-press)}
.notif-badge {
  position: absolute;
  top: -2px;right: -2px;
  width: 14px;height: 14px;
  background: var(--green);border-radius: 50%;
  font-size: 8px;color: #fff;
  display: flex;align-items: center;justify-content: center;
  font-weight: 700;
}
.avatar {
  width: 40px;height: 40px;border-radius: 50%;
  background: var(--bg);
  box-shadow: var(--neu-out-sm);
  display: flex;align-items: center;justify-content: center;
  font-size: 15px;font-weight: 700;
  color: var(--green);cursor: pointer;
  transition: var(--trans);
}
.avatar:hover{box-shadow:var(--neu-press)}

.stat-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}
.stat-card {
  background: var(--bg);
  border-radius: 20px;
  padding: 20px;
  box-shadow: var(--neu-out-sm);
  transition: var(--trans);
  cursor: default;
}
.stat-card:hover{box-shadow:5px 5px 14px var(--neu-dark),-3px -3px 10px var(--neu-light);transform:translateY(-2px)}
.sc-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.sc-label{font-size:12px;color:var(--text3);font-weight:500;letter-spacing:0.04em;text-transform:uppercase}
.sc-ico{font-size:20px}
.sc-val {
  font-family: var(--font-display);
  font-size: 28px;
  color: var(--green);
  line-height: 1;
  margin-bottom: 6px;
}
.sc-change{font-size:12px;color:var(--success);font-weight:500}

.dash-grid-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}
.dash-panel {
  background: var(--bg);
  border-radius: 20px;
  padding: 22px;
  box-shadow: var(--neu-out-sm);
}
.panel-title {
  font-family: var(--font-display);
  font-size: 16px;
  color: var(--text);
  margin-bottom: 18px;
}
.lang-row{margin-bottom:14px}
.lang-info{display:flex;justify-content:space-between;font-size:13px;margin-bottom:6px}
.lang-name{color:var(--text2);font-weight:500}
.lang-pct{color:var(--green);font-weight:600}
.lang-bar-bg {
  height: 7px;
  background: var(--bg2);
  border-radius: 4px;
  overflow: hidden;
  box-shadow: var(--neu-in);
}
.lang-bar {
  height: 100%;
  border-radius: 4px;
  animation: barGrow 1.2s ease forwards;
}
@keyframes barGrow{from{width:0}}
.lb1{background:linear-gradient(90deg,var(--green),var(--sage))}
.lb2{background:linear-gradient(90deg,var(--sage),var(--sage-lt))}
.lb3{background:linear-gradient(90deg,var(--gold),var(--gold-lt))}
.lb4{background:linear-gradient(90deg,var(--olive),var(--sage-lt))}
.lb5{background:linear-gradient(90deg,var(--green-dk),var(--green))}

.conv-item{display:flex;align-items:center;gap:10px;padding:10px 0;border-bottom:1px solid var(--border)}
.conv-item:last-child{border-bottom:none}
.conv-av {
  width:34px;height:34px;border-radius:50%;
  display:flex;align-items:center;justify-content:center;
  font-size:13px;font-weight:700;flex-shrink:0;
  background:var(--bg);box-shadow:var(--neu-out-sm);
  color:var(--green);
}
.conv-info{flex:1}
.conv-name{font-size:13px;font-weight:600;color:var(--text)}
.conv-preview{font-size:11px;color:var(--text3);margin-top:1px}
.conv-badge {
  padding:3px 10px;border-radius:10px;
  font-size:11px;font-weight:600;
  background:var(--bg3);color:var(--green);
  box-shadow:var(--neu-out-sm);
}

.fab {
  position: fixed;
  bottom: 32px;
  right: 32px;
  width: 56px;height: 56px;
  border-radius: 50%;
  background: var(--green);
  border: none;
  cursor: pointer;
  font-size: 22px;
  display: flex;
  align-items: center;justify-content: center;
  box-shadow: var(--neu-green);
  z-index: 999;
  transition: var(--trans);
  animation: fabPop 2.5s ease-in-out infinite;
}
.fab:hover{transform:scale(1.1);box-shadow:6px 6px 18px rgba(37,79,45,0.4),-2px -2px 8px #FFFFFF}
@keyframes fabPop{0%,100%{box-shadow:var(--neu-green)}50%{box-shadow:6px 6px 20px rgba(37,79,45,0.4),-2px -2px 10px #FFFFFF}}

/* ===== SECTION: CHAT ===== */
#chat{display:none;padding:0}
#chat.active{display:block}
.chat-layout {
  height: 100vh;
  display: flex;
  flex-direction: column;
  padding-top: 70px;
}
.chat-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 32px;
  background: var(--bg2);
  border-bottom: 1px solid var(--border);
}
.mode-selector{display:flex;gap:8px}
.mode-btn {
  padding: 7px 18px;
  border-radius: 18px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  background: var(--bg);
  box-shadow: var(--neu-out-sm);
  color: var(--text2);
  border: none;
  font-family: var(--font-body);
  transition: var(--trans);
}
.mode-btn:hover{color:var(--green)}
.mode-btn.active{background:var(--bg);box-shadow:var(--neu-press);color:var(--green);font-weight:600}
.lang-indicator{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--text2)}
.lang-orb {
  width:9px;height:9px;border-radius:50%;
  background:var(--sage);
  box-shadow:0 0 0 3px rgba(122,141,92,0.2);
  animation:langPop 2s ease-in-out infinite;
}
@keyframes langPop{0%,100%{box-shadow:0 0 0 2px rgba(122,141,92,0.15)}50%{box-shadow:0 0 0 6px rgba(122,141,92,0)}}

.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 24px 32px;
  display: flex;
  flex-direction: column;
  gap: 18px;
  background: var(--bg);
}
.chat-messages::-webkit-scrollbar{width:5px}
.chat-messages::-webkit-scrollbar-track{background:var(--bg2)}
.chat-messages::-webkit-scrollbar-thumb{background:var(--sage-lt);border-radius:3px}

.msg{display:flex;gap:10px;max-width:72%;animation:msgIn 0.35s ease}
@keyframes msgIn{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}
.msg.user{align-self:flex-end;flex-direction:row-reverse}
.msg-av {
  width:34px;height:34px;border-radius:50%;flex-shrink:0;
  background:var(--bg);box-shadow:var(--neu-out-sm);
  display:flex;align-items:center;justify-content:center;font-size:15px;
}
.msg-bubble {
  padding:13px 17px;
  border-radius:18px;
  font-size:14px;
  line-height:1.65;
  color:var(--text);
}
.msg.ai .msg-bubble {
  background:var(--bg);
  box-shadow:var(--neu-out-sm);
  border-radius:4px 18px 18px 18px;
}
.msg.user .msg-bubble {
  background:var(--green);
  color:#fff;
  border-radius:18px 4px 18px 18px;
  box-shadow:var(--neu-green);
}
.msg-lang{font-size:11px;color:var(--text3);margin-top:5px;padding-left:4px}

/* Typing indicator */
.typing-wrap{display:flex;gap:10px}
.typing-bubble {
  display:flex;align-items:center;gap:6px;
  padding:13px 18px;
  background:var(--bg);
  box-shadow:var(--neu-out-sm);
  border-radius:4px 18px 18px 18px;
}
.t-dot {
  width:7px;height:7px;border-radius:50%;
  background:var(--sage);
  animation:tBounce 1.1s ease-in-out infinite;
}
.t-dot:nth-child(2){animation-delay:0.18s}
.t-dot:nth-child(3){animation-delay:0.36s}
@keyframes tBounce{0%,80%,100%{transform:scale(0.5);opacity:0.3}40%{transform:scale(1);opacity:1}}

.chat-input-area {
  padding: 16px 28px;
  background: var(--bg2);
  border-top: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: 10px;
}
.chat-input-box {
  flex: 1;
  background: var(--bg);
  box-shadow: var(--neu-in);
  border: 1px solid var(--border);
  border-radius: 26px;
  padding: 12px 22px;
  color: var(--text);
  font-size: 14px;
  font-family: var(--font-body);
  outline: none;
  transition: var(--trans);
}
.chat-input-box:focus{box-shadow:inset 4px 4px 10px #C8BB9F,inset -3px -3px 8px #FFFFFF,0 0 0 2px rgba(122,141,92,0.35);border-color:var(--sage)}
.chat-input-box::placeholder{color:var(--textd)}
.send-btn,.mic-btn {
  width: 44px;height: 44px;border-radius: 50%;
  border: none;cursor: pointer;
  display: flex;align-items: center;justify-content: center;
  font-size: 18px;
  transition: var(--trans);
}
.send-btn {
  background:var(--green);color:#fff;
  box-shadow:var(--neu-green);
}
.send-btn:hover{transform:scale(1.08);background:var(--green-dk)}
.send-btn:active{transform:scale(0.96);box-shadow:var(--neu-press)}
.mic-btn {
  background:var(--bg);color:var(--green);
  box-shadow:var(--neu-out-sm);
}
.mic-btn:hover{box-shadow:var(--neu-out);color:var(--sage)}
.mic-btn:active,.mic-btn.jarvis-active {
  box-shadow:var(--neu-press);
  background:var(--bg3);
  color:var(--green);
  animation:micActive 1s ease-in-out infinite;
}
@keyframes micActive{0%,100%{box-shadow:var(--neu-press)}50%{box-shadow:3px 3px 10px rgba(37,79,45,0.3),-2px -2px 8px #FFFFFF}}

/* ===== JARVIS OVERLAY ===== */
#jarvis-overlay {
  display:none;
  position:fixed;inset:0;z-index:9999;
  background:rgba(244,235,221,0.88);
  backdrop-filter:blur(20px);
  -webkit-backdrop-filter:blur(20px);
  flex-direction:column;align-items:center;justify-content:center;gap:22px;
}
#jarvis-overlay.active{display:flex}

.jarvis-ring-wrap{position:relative;width:260px;height:260px;display:flex;align-items:center;justify-content:center}
.jarvis-ring {
  position:absolute;border-radius:50%;
  border-style:solid;border-color:transparent;
  animation-timing-function:linear;animation-iteration-count:infinite;
}
.jr1{width:260px;height:260px;border-width:2px;border-top-color:rgba(37,79,45,0.7);border-right-color:rgba(37,79,45,0.12);animation:jspin 1.5s linear infinite}
.jr2{width:220px;height:220px;border-width:1.5px;border-top-color:rgba(199,168,107,0.8);border-left-color:rgba(199,168,107,0.15);animation:jspin2 2.2s linear infinite}
.jr3{width:182px;height:182px;border-width:1px;border-top-color:rgba(122,141,92,0.6);border-right-color:rgba(122,141,92,0.1);animation:jspin 3s linear infinite reverse}
.jr4{width:146px;height:146px;border-width:1.5px;border-top-color:rgba(37,79,45,0.4);border-left-color:rgba(37,79,45,0.06);animation:jspin2 1.9s linear infinite}
@keyframes jspin{to{transform:rotate(360deg)}}
@keyframes jspin2{to{transform:rotate(-360deg)}}
.jarvis-core {
  position:relative;z-index:2;
  width:80px;height:80px;border-radius:50%;
  background:var(--bg);
  box-shadow:var(--neu-out-sm);
  display:flex;align-items:center;justify-content:center;
  font-size:32px;
  animation:corePulse 1.4s ease-in-out infinite;
}
@keyframes corePulse{0%,100%{box-shadow:var(--neu-out-sm)}50%{box-shadow:5px 5px 14px rgba(37,79,45,0.2),-2px -2px 8px #FFFFFF}}

.jarvis-bars{display:flex;align-items:center;gap:5px;height:48px}
.jbar{
  width:5px;border-radius:3px;
  background:linear-gradient(to top,var(--green),var(--sage));
  animation:jbarAnim 0.55s ease-in-out infinite alternate;
  transform-origin:bottom;
}
.jbar:nth-child(1){height:10px;animation-delay:0s}.jbar:nth-child(2){height:24px;animation-delay:.08s}.jbar:nth-child(3){height:38px;animation-delay:.16s}.jbar:nth-child(4){height:48px;animation-delay:.24s}.jbar:nth-child(5){height:36px;animation-delay:.32s}.jbar:nth-child(6){height:44px;animation-delay:.40s}.jbar:nth-child(7){height:28px;animation-delay:.48s}.jbar:nth-child(8){height:14px;animation-delay:.56s}
@keyframes jbarAnim{from{transform:scaleY(0.25);opacity:0.35}to{transform:scaleY(1);opacity:1}}
.jbar.idle{animation:none;transform:scaleY(0.2);opacity:0.25}

.jarvis-status {
  font-family:var(--font-display);font-size:22px;
  color:var(--green);text-align:center;
}
.jarvis-sub{font-size:14px;color:var(--text3);text-align:center;margin-top:-14px}
.jarvis-btns{display:flex;gap:12px;margin-top:6px}
.jarvis-close-btn {
  padding:9px 24px;border-radius:22px;
  background:var(--bg);box-shadow:var(--neu-out-sm);
  border:none;color:var(--text2);font-size:13px;font-weight:500;
  cursor:pointer;font-family:var(--font-body);
  transition:var(--trans);
}
.jarvis-close-btn:hover{box-shadow:var(--neu-press);color:var(--green)}
#jarvis-send-btn{display:none;background:var(--green);color:#fff;box-shadow:var(--neu-green)}
#jarvis-send-btn:hover{background:var(--green-dk)}

/* ===== SECTION: FOOTER ===== */
#footer-sec{display:none;min-height:auto;padding:0}
#footer-sec.active{display:block}
.footer-glow{height:3px;background:linear-gradient(90deg,transparent,var(--green),var(--gold),transparent)}
.footer-body{background:var(--bg2);padding:60px 48px 40px}
.footer-top{display:grid;grid-template-columns:2fr 1fr 1fr 1fr;gap:40px;margin-bottom:50px}
.footer-logo {
  font-family:var(--font-display);font-size:22px;
  color:var(--green);margin-bottom:14px;display:block;
}
.footer-brand p{font-size:14px;color:var(--text2);line-height:1.7;max-width:260px;margin-bottom:20px}
.footer-socials{display:flex;gap:10px}
.social-btn {
  width:36px;height:36px;border-radius:50%;
  background:var(--bg);box-shadow:var(--neu-out-sm);
  display:flex;align-items:center;justify-content:center;
  font-size:14px;cursor:pointer;
  border:none;color:var(--text2);
  transition:var(--trans);text-decoration:none;
}
.social-btn:hover{box-shadow:var(--neu-press);color:var(--green)}
.footer-col h4{font-size:13px;font-weight:600;color:var(--green);margin-bottom:18px;letter-spacing:0.05em;text-transform:uppercase}
.footer-col a{display:block;font-size:14px;color:var(--text2);text-decoration:none;margin-bottom:11px;transition:color 0.2s}
.footer-col a:hover{color:var(--green)}
.footer-bottom{display:flex;align-items:center;justify-content:space-between;padding-top:28px;border-top:1px solid var(--border);flex-wrap:wrap;gap:14px}
.footer-copy{font-size:13px;color:var(--text3)}
.powered-badge {
  display:inline-flex;align-items:center;gap:8px;
  background:var(--bg);box-shadow:var(--neu-out-sm);
  border-radius:18px;padding:7px 18px;
  font-size:13px;color:var(--text2);
}
.powered-badge strong{color:var(--green);font-weight:700}

/* ===== RESPONSIVE ===== */
@media(max-width:768px){
  nav{padding:0 20px}
  .nav-links{gap:2px}
  .nav-link{padding:6px 12px;font-size:13px}
  section{padding:80px 20px 60px}
  .hero-headline{font-size:42px;letter-spacing:-1px}
  .feat-grid,.stat-cards,.dash-grid-2{grid-template-columns:1fr}
  .dash-layout{flex-direction:column}
  .dash-sidebar{width:100%;padding:12px 0;display:flex;overflow-x:auto;border-right:none;border-bottom:1px solid var(--border)}
  .dash-main{padding:16px}
  .footer-top{grid-template-columns:1fr 1fr}
  .stats-bar{flex-direction:column;border-radius:20px}
  .stat-item{border-right:none;border-bottom:1px solid var(--border)}
  .stat-item:last-child{border-bottom:none}
  .hero-visual{width:260px;height:260px}
  .hero-orb{width:260px;height:260px}
  .orb-inner{width:170px;height:170px}
}

/* ===== SCROLLBAR ===== */
::-webkit-scrollbar{width:6px}
::-webkit-scrollbar-track{background:var(--bg2)}
::-webkit-scrollbar-thumb{background:var(--sage-lt);border-radius:3px}
::-webkit-scrollbar-thumb:hover{background:var(--sage)}

/* ===== SMOOTH MICRO-INTERACTIONS ===== */
@media(prefers-reduced-motion:reduce){
  *{animation-duration:0.01ms!important;transition-duration:0.01ms!important}
}
</style>
</head>
<body>

<!-- Ambient background blobs -->
<div class="ambient">
  <div class="amb-blob"></div>
  <div class="amb-blob"></div>
  <div class="amb-blob"></div>
</div>

<!-- JARVIS OVERLAY -->
<div id="jarvis-overlay">
  <div class="jarvis-ring-wrap">
    <div class="jarvis-ring jr1"></div>
    <div class="jarvis-ring jr2"></div>
    <div class="jarvis-ring jr3"></div>
    <div class="jarvis-ring jr4"></div>
    <div class="jarvis-core" id="jarvis-core-icon">🎙️</div>
  </div>
  <div class="jarvis-bars" id="jarvis-bars">
    <div class="jbar idle"></div><div class="jbar idle"></div><div class="jbar idle"></div><div class="jbar idle"></div>
    <div class="jbar idle"></div><div class="jbar idle"></div><div class="jbar idle"></div><div class="jbar idle"></div>
  </div>
  <div class="jarvis-status" id="jarvis-status">Initializing...</div>
  <div class="jarvis-sub" id="jarvis-sub">Tamil · Hindi · English supported</div>
  <div class="jarvis-btns">
    <button class="jarvis-close-btn" id="jarvis-send-btn">📤 Send</button>
    <button class="jarvis-close-btn" onclick="cancelJarvis()">✕ End Conversation</button>
  </div>
</div>

<!-- NAV -->
<nav>
  <div class="nav-logo" onclick="showSection('landing')">
    <div class="logo-orb">⚡</div>
    Samvad AI
  </div>
  <div class="nav-links">
    <button class="nav-link active" id="nav-landing" onclick="showSection('landing')">Home</button>
    <button class="nav-link" id="nav-features" onclick="showSection('features')">Features</button>
    <button class="nav-link" id="nav-dashboard" onclick="showSection('dashboard')">Dashboard</button>
    <button class="nav-link" id="nav-chat" onclick="showSection('chat')">Chat</button>
    <button class="nav-link" id="nav-footer-sec" onclick="showSection('footer-sec')">About</button>
    <button class="nav-cta" onclick="showSection('chat')">Start Free →</button>
  </div>
</nav>

<div class="page">

<!-- LANDING -->
<section id="landing" class="active">
  <div class="hero-badge">
    <span class="badge-dot"></span>
    Now live in India 🇮🇳 · FlowZint AI Hackathon 2026
  </div>

  <h1 class="hero-headline">
    <em>Samvad AI —</em><br>
    Talk to the <span class="accent-word">Future</span><br>
    of Business
  </h1>

  <p class="hero-sub">
    AI-Powered Communication for Bharat. Multi-language, real-time, intelligent conversations — built for India.
  </p>

  <div class="hero-btns">
    <button class="btn-primary-solid" onclick="showSection('chat')">Start Chatting 🚀</button>
    <button class="btn-neu" onclick="showSection('features')">Explore Features</button>
  </div>

  <!-- Hero sphere visual -->
  <div class="hero-visual">
    <div class="hero-orb">
      <div class="orb-inner">
        <div class="orb-text">Samvad</div>
        <div class="orb-sub">AI Platform</div>
      </div>
    </div>
    <div class="orbit-chip chip1">🌐 Tamil</div>
    <div class="orbit-chip chip2">🎙️ Voice</div>
    <div class="orbit-chip chip3">🤖 AI</div>
    <div class="orbit-chip chip4">⚡ Real-time</div>
  </div>

  <!-- Stats bar -->
  <div class="stats-bar">
    <div class="stat-item">
      <span class="stat-num" id="stat-convos">1M+</span>
      <div class="stat-label">Conversations</div>
    </div>
    <div class="stat-item">
      <span class="stat-num">99%</span>
      <div class="stat-label">Uptime</div>
    </div>
    <div class="stat-item">
      <span class="stat-num">6+</span>
      <div class="stat-label">Languages</div>
    </div>
    <div class="stat-item">
      <span class="stat-num">500+</span>
      <div class="stat-label">Businesses</div>
    </div>
  </div>
</section>

<!-- FEATURES -->
<section id="features">
  <div class="sec-header">
    <div class="sec-eyebrow">Why Samvad AI</div>
    <h2 class="sec-title">Built ground-up<br>for <span>Indian businesses</span></h2>
    <p class="sec-sub">Every feature designed for Bharat — multilingual by default, intelligent by design.</p>
  </div>
  <div class="feat-grid">
    <div class="feat-card">
      <div class="feat-icon">🌐</div>
      <h3>6+ Indian Languages</h3>
      <p>Auto-detect and respond in Tamil, Hindi, Kannada, Telugu, Malayalam and more. Even Tanglish and Hinglish work seamlessly.</p>
      <span class="feat-tag">NLP Engine v3</span>
    </div>
    <div class="feat-card">
      <div class="feat-icon">🎙️</div>
      <h3>Speech-to-Speech</h3>
      <p>Speak in your language. The AI listens, understands, and speaks back — a true voice-to-voice Jarvis-style experience.</p>
      <span class="feat-tag">Real-time Voice</span>
    </div>
    <div class="feat-card">
      <div class="feat-icon">🤖</div>
      <h3>Smart AI Agents</h3>
      <p>Sales, Support, and Customer Care — three specialized AI modes that adapt their persona and tone automatically per interaction.</p>
      <span class="feat-tag">3 Agent Modes</span>
    </div>
    <div class="feat-card">
      <div class="feat-icon">📊</div>
      <h3>Live Analytics</h3>
      <p>Track conversations, leads, and resolution rates on a beautiful dashboard. Language distribution, response times — all live.</p>
      <span class="feat-tag">Live Dashboard</span>
    </div>
  </div>
</section>

<!-- DASHBOARD -->
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
        <div class="dash-welcome">
          <h2>Welcome back! 👋</h2>
          <p id="dash-date">Loading...</p>
        </div>
        <div class="dash-actions">
          <button class="notif-btn">🔔<span class="notif-badge">3</span></button>
          <div class="avatar">M</div>
        </div>
      </div>
      <div class="stat-cards">
        <div class="stat-card">
          <div class="sc-top"><span class="sc-label">Total Chats</span><span class="sc-ico">💬</span></div>
          <div class="sc-val" id="dash-total">0</div>
          <div class="sc-change">↑ Live</div>
        </div>
        <div class="stat-card">
          <div class="sc-top"><span class="sc-label">AI Resolution</span><span class="sc-ico">✅</span></div>
          <div class="sc-val">89%</div>
          <div class="sc-change">↑ 3% this week</div>
        </div>
        <div class="stat-card">
          <div class="sc-top"><span class="sc-label">Leads Captured</span><span class="sc-ico">👤</span></div>
          <div class="sc-val">342</div>
          <div class="sc-change">↑ 8% this week</div>
        </div>
        <div class="stat-card">
          <div class="sc-top"><span class="sc-label">Avg Response</span><span class="sc-ico">⚡</span></div>
          <div class="sc-val">3.2s</div>
          <div class="sc-change">↓ 0.4s faster</div>
        </div>
      </div>
      <div class="dash-grid-2">
        <div class="dash-panel" id="lang-panel">
          <div class="panel-title">Language Distribution</div>
          <p style="color:var(--text3);font-size:13px">No conversations yet — start chatting!</p>
        </div>
        <div class="dash-panel" id="recent-panel">
          <div class="panel-title">Recent Conversations</div>
          <p style="color:var(--text3);font-size:13px">No conversations yet — start chatting!</p>
        </div>
      </div>
    </div>
  </div>
  <button class="fab" onclick="showSection('chat')" title="New Chat">💬</button>
</section>

<!-- CHAT -->
<section id="chat">
  <div class="chat-layout">
    <div class="chat-topbar">
      <div class="mode-selector">
        <button class="mode-btn active" onclick="setMode(this,'support')">🎧 Support</button>
        <button class="mode-btn" onclick="setMode(this,'sales')">💼 Sales</button>
        <button class="mode-btn" onclick="setMode(this,'customer')">🤝 Customer Care</button>
      </div>
      <div class="lang-indicator">
        <div class="lang-orb"></div>
        <span id="lang-display">Ready...</span>
      </div>
    </div>

    <div class="chat-messages" id="chat-messages">
      <div class="msg ai">
        <div class="msg-av">🤖</div>
        <div>
          <div class="msg-bubble">Vanakkam! 🙏 Naan Samvad AI — FlowZint-oda intelligent assistant. Tamil, Hindi, English, Tanglish, Hinglish — ellam pesuvom! Unga business-ku epdi help pannalaam?</div>
          <div class="msg-lang">🇮🇳 Tamil · Hindi · English · Tanglish · Hinglish · +2 more</div>
        </div>
      </div>
    </div>

    <div class="chat-input-area">
      <button class="mic-btn" id="micBtn" title="Voice Conversation">🎙️</button>
      <input class="chat-input-box" id="chat-input" type="text" placeholder="Type in Tamil / Hindi / Tanglish / Hinglish..." maxlength="300">
      <button class="send-btn" onclick="sendChatMsg(false)" title="Send">➤</button>
    </div>
  </div>
</section>

<!-- ABOUT / FOOTER -->
<section id="footer-sec">
  <div class="footer-glow"></div>
  <div class="footer-body">
    <div class="footer-top">
      <div class="footer-brand">
        <span class="footer-logo">⚡ Samvad AI</span>
        <p>AI-Powered Business Communication for India. Multi-language, real-time, intelligent conversations at scale — built for Bharat.</p>
        <div class="footer-socials">
          <a class="social-btn">𝕏</a>
          <a class="social-btn">in</a>
          <a class="social-btn">▶</a>
          <a class="social-btn">💬</a>
        </div>
      </div>
      <div class="footer-col">
        <h4>Product</h4>
        <a href="#">Features</a>
        <a href="#">Pricing</a>
        <a href="#">API Docs</a>
        <a href="#">Changelog</a>
      </div>
      <div class="footer-col">
        <h4>Company</h4>
        <a href="#">About Us</a>
        <a href="#">Blog</a>
        <a href="#">Careers</a>
        <a href="#">Contact</a>
      </div>
      <div class="footer-col">
        <h4>Legal</h4>
        <a href="#">Privacy Policy</a>
        <a href="#">Terms of Service</a>
        <a href="#">Security</a>
        <a href="#">Cookie Policy</a>
      </div>
    </div>
    <div class="footer-bottom">
      <div class="footer-copy">© 2026 Samvad AI. Built for FlowZint AI Hackathon 2026. Made with ❤️ in India 🇮🇳</div>
      <div class="powered-badge">⚡ In partnership with <strong>FlowZint</strong></div>
    </div>
  </div>
</section>

</div><!-- .page -->

<script>
// ===== LANGUAGE DETECTION =====
const TAMIL_KEYWORDS = new Set(['naan','nee','avan','aval','ivanga','avanga','unga','en','enakku','yennakku','ennaku','enna','yaaru','eppadi','ippo','appo','apram','pannu','pannunga','sollu','sollunga','pesu','pesanum','poga','vaa','vaanga','irukku','irukka','iruken','theriyum','theriyathu','mudiyum','venda','vendam','vendum','venum','nalla','romba','konjam','seri','sari','aama','therla','puriyala','puriyuthu','enga','inge','ange','vanakkam','machan','da','di','bro','akka','anna']);
const HINDI_KEYWORDS = new Set(['aap','tum','mai','hum','usne','mujhe','kya','kaise','kab','kahan','kyu','kaun','hai','hain','hoon','the','thi','raha','rahi','kar','karo','karna','karta','karte','jao','jaana','aao','batana','batao','bataiye','sunna','suno','dekho','acha','theek','sahi','nahi','haan','ji','bhai','behan','mera','tera','uska','chahiye','abhi','kal','aaj','yaar','bahut','bilkul','zaroor','namaste','kaam','paisa']);
const ENGLISH_COMMON = new Set(['hello','hi','hey','yes','no','ok','okay','thanks','thank','please','help','sorry','good','bad','fine','great','awesome','cool','nice','love','like','want','need','get','have','do','go','come','see','look','tell','say','ask','know','think','feel','work','time','day','week','today','tomorrow','now','later','always','never','maybe','really','very','too','also','just','only','still','ever','once']);

function detectLang(text) {
  if (!text.trim()) return 'English';
  if (/[\u0B80-\u0BFF]/.test(text)) return 'Tamil';
  if (/[\u0900-\u097F]/.test(text)) return 'Hindi';
  const lower = text.toLowerCase().replace(/[^a-z0-9 ]/g,' ');
  const words = lower.split(/\s+/);
  let tm=0,hi=0,en=0;
  for (const w of words) {
    if (TAMIL_KEYWORDS.has(w)) tm++;
    if (HINDI_KEYWORDS.has(w)) hi++;
    if (ENGLISH_COMMON.has(w)) en++;
  }
  if (tm > hi && tm >= 2) return 'Tamil';
  if (hi > tm && hi >= 2) return 'Hindi';
  if (en >= 2) return 'English';
  if (tm >= 1) return 'Tamil';
  if (hi >= 1) return 'Hindi';
  return 'English';
}
function getLangCode(ld) {
  if (ld==='Tamil') return 'ta';
  if (ld==='Hindi') return 'hi';
  return 'en';
}

// ===== SECTION NAVIGATION =====
function showSection(id) {
  document.querySelectorAll('section').forEach(s => {
    s.style.display = 'none';
    s.classList.remove('active');
  });
  document.querySelectorAll('.nav-link').forEach(a => a.classList.remove('active'));
  const t = document.getElementById(id);
  if (t) {
    t.classList.add('active');
    if (id === 'landing') t.style.display = 'flex';
    else t.style.display = 'block';
  }
  const nav = document.getElementById('nav-' + id);
  if (nav) nav.classList.add('active');
  window.scrollTo(0,0);
  if (id === 'dashboard') { loadDashboardStats(); loadRecentConversations(); }
}

// Set date
document.getElementById('dash-date').textContent = new Date().toLocaleDateString('en-IN',{weekday:'long',year:'numeric',month:'long',day:'numeric'}) + ' · All systems operational';

// ===== MODE =====
let chatMode = 'support';
function setMode(btn, mode) {
  document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  chatMode = mode;
}

// ===== TTS =====
let audioEl = null;
function cancelTTS() {
  if (audioEl) { audioEl.pause(); audioEl.currentTime = 0; audioEl = null; }
  if (window.speechSynthesis) window.speechSynthesis.cancel();
}

function speakText(text, lang, cb) {
  if (!text) { if(cb) cb(); return; }
  const lc = getLangCode(lang);
  fetch('/api/tts', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({text, lang: lc}) })
    .then(r => r.json())
    .then(d => {
      if (d.audio) {
        cancelTTS();
        audioEl = new Audio('data:audio/mp3;base64,' + d.audio);
        audioEl.onended = () => { audioEl=null; if(cb) cb(); };
        audioEl.onerror = () => { audioEl=null; fallbackTTS(text, lang, cb); };
        audioEl.play().catch(() => { audioEl=null; fallbackTTS(text, lang, cb); });
      } else fallbackTTS(text, lang, cb);
    }).catch(() => fallbackTTS(text, lang, cb));
}

function fallbackTTS(text, lang, cb) {
  if (!window.speechSynthesis) { if(cb) cb(); return; }
  const u = new SpeechSynthesisUtterance(text);
  const map = {Tamil:'ta-IN',Hindi:'hi-IN',English:'en-US'};
  u.lang = map[lang] || 'en-US';
  u.rate = 0.9;
  u.onend = u.onerror = () => { if(cb) cb(); };
  window.speechSynthesis.speak(u);
}

// ===== JARVIS VOICE =====
let jarvisActive = false, isProcessing = false;
let jarvisRecognition = null;

function showJarvis(status, sub, listening) {
  document.getElementById('jarvis-overlay').classList.add('active');
  document.getElementById('jarvis-status').textContent = status;
  document.getElementById('jarvis-sub').textContent = sub || 'Tamil · Hindi · English supported';
  document.getElementById('jarvis-core-icon').textContent = listening ? '🎙️' : '🤖';
  document.querySelectorAll('.jbar').forEach(b => b.classList.toggle('idle', !listening));
}
function hideJarvis() {
  document.getElementById('jarvis-overlay').classList.remove('active');
  document.getElementById('micBtn').classList.remove('jarvis-active');
  jarvisActive = false;
  if (jarvisRecognition) try { jarvisRecognition.stop(); } catch(e) {}
  cancelTTS();
}
function cancelJarvis() {
  isProcessing = false;
  if (jarvisRecognition) try { jarvisRecognition.stop(); } catch(e) {}
  cancelTTS();
  hideJarvis();
}

function startListening() {
  if (!jarvisActive || isProcessing) return;
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { alert('Speech recognition not supported in this browser.'); return; }
  if (jarvisRecognition) try { jarvisRecognition.stop(); } catch(e) {}

  const recognition = new SR();
  jarvisRecognition = recognition;
  const langs = ['ta-IN','hi-IN','en-US'];
  let li = 0;
  recognition.lang = langs[li];
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.maxAlternatives = 1;
  let finalText = '', interimText = '', silenceTimer = null;

  recognition.onstart = () => {
    showJarvis('Listening...', {0:'Tamil',1:'Hindi',2:'English'}[li] + ' mode', true);
    finalText = ''; interimText = '';
    document.getElementById('jarvis-send-btn').style.display = 'inline-block';
    document.getElementById('jarvis-send-btn').onclick = () => {
      if (silenceTimer) clearTimeout(silenceTimer);
      const t = finalText + interimText;
      if (t.trim()) processVoiceInput(t);
    };
  };

  recognition.onresult = (event) => {
    if (audioEl || (window.speechSynthesis && window.speechSynthesis.speaking)) cancelTTS();
    if (silenceTimer) clearTimeout(silenceTimer);
    let interim = '';
    for (let i = event.resultIndex; i < event.results.length; i++) {
      if (event.results[i].isFinal) finalText += event.results[i][0].transcript;
      else interim += event.results[i][0].transcript;
    }
    interimText = interim;
    const display = finalText + interim;
    if (display) {
      document.getElementById('jarvis-status').textContent = display.length > 44 ? display.substring(0,44)+'...' : display;
      document.getElementById('jarvis-sub').textContent = 'Detected: ' + detectLang(display);
    }
    silenceTimer = setTimeout(() => {
      if ((finalText + interimText).trim()) processVoiceInput(finalText + interimText);
    }, 2800);
  };

  recognition.onerror = (e) => {
    if (e.error === 'not-allowed') { alert('Please allow microphone access.'); cancelJarvis(); return; }
    if (li < langs.length - 1) { li++; recognition.lang = langs[li]; }
    if (jarvisActive && !isProcessing) setTimeout(() => startListening(), 400);
  };

  recognition.onend = () => {
    if (jarvisActive && !isProcessing) {
      const t = finalText + interimText;
      if (t.trim()) processVoiceInput(t);
      else setTimeout(() => startListening(), 350);
    }
  };

  recognition.start();
}

function processVoiceInput(text) {
  if (!text.trim() || isProcessing) return;
  isProcessing = true;
  if (jarvisRecognition) try { jarvisRecognition.stop(); } catch(e) {}
  showJarvis('Processing...', 'AI is thinking...', false);
  document.getElementById('jarvis-send-btn').style.display = 'none';
  document.getElementById('chat-input').value = text.trim();
  sendChatMsg(true).then(() => {
    isProcessing = false;
    if (jarvisActive) setTimeout(() => startListening(), 700);
  }).catch(() => {
    isProcessing = false;
    if (jarvisActive) setTimeout(() => startListening(), 700);
  });
}

document.getElementById('micBtn').addEventListener('click', function() {
  if (jarvisActive) { cancelJarvis(); return; }
  if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
    alert('Voice input requires Chrome or Safari browser.');
    return;
  }
  jarvisActive = true;
  isProcessing = false;
  this.classList.add('jarvis-active');
  showJarvis('Samvad AI initializing...', 'Starting up...', false);
  const greets = [
    {lang:'Tamil', text:'Vanakkam! Naan Samvad AI. Enna help pannalaam?', code:'ta'},
    {lang:'Hindi', text:'Namaste! Main Samvad AI hoon. Kaise help karoon?', code:'hi'},
    {lang:'English', text:'Hello! I am Samvad AI. How can I help you today?', code:'en'}
  ];
  const g = greets[Math.floor(Math.random() * greets.length)];
  showJarvis('Hello! Pesungal...', g.lang + ' ready', true);
  speakText(g.text, g.lang, () => { if (jarvisActive) startListening(); });
});

// ===== CHAT =====
let isTyping = false;
window.convId = null;

async function sendChatMsg(shouldSpeak = false) {
  if (isTyping) return;
  const inp = document.getElementById('chat-input');
  const txt = inp.value.trim();
  if (!txt) return;
  inp.value = '';

  const lang = detectLang(txt);
  document.getElementById('lang-display').textContent = 'Detected: ' + lang;

  const msgs = document.getElementById('chat-messages');
  const uDiv = document.createElement('div');
  uDiv.className = 'msg user';
  uDiv.innerHTML = `<div class="msg-av">👤</div><div><div class="msg-bubble">${txt}</div><div class="msg-lang">${lang}</div></div>`;
  msgs.appendChild(uDiv);

  const tid = 'typing-' + Date.now();
  const tDiv = document.createElement('div');
  tDiv.className = 'msg ai';
  tDiv.id = tid;
  tDiv.innerHTML = `<div class="msg-av">🤖</div><div class="typing-bubble"><div class="t-dot"></div><div class="t-dot"></div><div class="t-dot"></div></div>`;
  msgs.appendChild(tDiv);
  msgs.scrollTop = msgs.scrollHeight;
  isTyping = true;

  try {
    const res = await fetch('/api/chat-stream', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({message: txt, mode: chatMode, conversation_id: window.convId || null})
    });
    if (!res.ok) throw new Error('Server error');

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let aiReply = '';

    document.getElementById(tid)?.remove();
    const mid = 'ai-msg-' + Date.now();
    const aiDiv = document.createElement('div');
    aiDiv.className = 'msg ai';
    aiDiv.id = mid;
    aiDiv.innerHTML = `<div class="msg-av">🤖</div><div><div class="msg-bubble" id="bubble-${mid}"></div><div class="msg-lang">🤖 Samvad AI · ${chatMode} · ${lang}</div></div>`;
    msgs.appendChild(aiDiv);
    const bubble = document.getElementById('bubble-' + mid);

    while(true) {
      const {done, value} = await reader.read();
      if (done) break;
      for (const line of decoder.decode(value).split('\n')) {
        if (line.startsWith('data: ')) {
          const c = line.substring(6);
          if (c === '[DONE]') break;
          aiReply += c;
          if (bubble) bubble.textContent = aiReply;
          msgs.scrollTop = msgs.scrollHeight;
        }
      }
    }

    if (shouldSpeak === true) {
      await new Promise(resolve => speakText(aiReply, lang, resolve));
    }
    return aiReply;
  } catch(err) {
    document.getElementById(tid)?.remove();
    const errDiv = document.createElement('div');
    errDiv.className = 'msg ai';
    errDiv.innerHTML = `<div class="msg-av">🤖</div><div><div class="msg-bubble">⚠️ Server error — is the Flask backend running? Make sure to run the Python server and set GROQ_API_KEY.</div></div>`;
    msgs.appendChild(errDiv);
    throw err;
  } finally {
    msgs.scrollTop = msgs.scrollHeight;
    isTyping = false;
  }
}

document.getElementById('chat-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') { e.preventDefault(); sendChatMsg(false); }
});

// ===== DASHBOARD =====
async function loadDashboardStats() {
  try {
    const res = await fetch('/api/stats');
    const data = await res.json();
    const total = data.total_conversations || 0;
    document.getElementById('dash-total').textContent = total;
    document.getElementById('stat-convos').textContent = total > 1000 ? Math.round(total/1000)+'K+' : total+'';
    const langs = data.languages || {};
    const lp = document.getElementById('lang-panel');
    const colors = ['lb1','lb2','lb3','lb4','lb5'];
    let html = '<div class="panel-title">Language Distribution</div>';
    let i = 0;
    const t = Object.values(langs).reduce((a,b) => a+b, 0) || 1;
    for (const [name, count] of Object.entries(langs)) {
      const pct = Math.round((count/t)*100);
      html += `<div class="lang-row"><div class="lang-info"><span class="lang-name">${name}</span><span class="lang-pct">${pct}%</span></div><div class="lang-bar-bg"><div class="lang-bar ${colors[i%5]}" style="width:${pct}%"></div></div></div>`;
      i++;
    }
    if (!i) html += '<p style="color:var(--text3);font-size:13px">No conversations yet — start chatting!</p>';
    lp.innerHTML = html;
  } catch(e) { console.log('Stats error:', e); }
}

async function loadRecentConversations() {
  try {
    const res = await fetch('/api/history');
    const convos = await res.json();
    const panel = document.getElementById('recent-panel');
    let html = '<div class="panel-title">Recent Conversations</div>';
    const recent = convos.slice(-4).reverse();
    if (!recent.length) { html += '<p style="color:var(--text3);font-size:13px">No conversations yet — start chatting!</p>'; }
    else {
      recent.forEach((c, idx) => {
        const emojis = ['🌿','🌾','🍃','🌱'];
        html += `<div class="conv-item"><div class="conv-av">${emojis[idx%4]}</div><div class="conv-info"><div class="conv-name">${c.id}</div><div class="conv-preview">${c.count} messages · ${c.mode}</div></div><span class="conv-badge">${c.language}</span></div>`;
      });
    }
    panel.innerHTML = html;
  } catch(e) { console.log('History error:', e); }
}

// ===== INIT =====
showSection('landing');
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

    system_prompt = f"""You are Samvad AI - FlowZint's intelligent assistant.
Current Mode: {mode.upper()}
{MODE_PROMPTS.get(mode, MODE_PROMPTS['support'])}

🚨 **LANGUAGE LOCK (DO NOT BREAK)** 🚨
The user wrote in: {lang}.
You MUST reply ONLY in {lang} language.
- If {lang} is Tamil -> Reply in Tamil script (அ ஆ இ).
- If {lang} is Hindi -> Reply in Hindi script (अ आ इ).
- If {lang} is English -> Reply in English.
NEVER reply in English if user wrote in Tamil or Hindi.
NEVER mix languages. Output 100% pure {lang}.

RULES:
- Keep replies SHORT: 2-3 sentences.
- Be warm, conversational.
- Use respectful terms.
"""
    
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
        'version':'18.1 - FIXED LANGUAGE DETECTION'
    })

if __name__ == '__main__':
    port = int(os.getenv("PORT",5000))
    print("\n" + "="*70)
    print("  SAMVAD AI v18.1 - FIXED LANGUAGE DETECTION")
    print("="*70)
    print(f"  Server   : http://localhost:{port}")
    print(f"  Groq AI  : {'READY' if client else 'Set GROQ_API_KEY'}")
    print(f"  gTTS     : {'INSTALLED' if GTTS_AVAILABLE else 'Run: pip install gTTS'}")
    print("="*70)
    print("  ✅ Language detection now balances Tamil, Hindi, and English.")
    print("  ✅ AI replies in your language.")
    print("="*70+"\n")
    app.run(debug=False, host='0.0.0.0', port=port)