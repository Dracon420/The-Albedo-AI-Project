"""
generate_all_datasets.py — Comprehensive dataset generator for all Albedo training rounds.

Runs on Azure VM using the Gemini API. Generates:
  /data/albedo_dataset_v5.jsonl     — Cortana R4 (new examples, merged with v4 by train script)
  /data/jarvis_dataset_v4.jsonl     — JARVIS R4 (new examples, merged with v3 by train script)
  /data/jarvis_tech_dataset_v1.jsonl — JARVIS-Tech LoRA (code + embedded + electronics)

Coverage beyond R3:
  Cortana new categories:
    - PC hardware anti-hallucination (ground-truth GPU/CPU/RAM facts, myth-busting)
    - File system safety (what to move, what NOT to touch, Windows internals)
    - STT/voice query handling (transcription-aware, graceful ambiguity)
    - Advanced 3D printing (Klipper, multi-material, calibration, resin)
    - Advanced reptile husbandry (health, breeding, species-specific)
    - Windows PowerShell scripting and automation
    - Home networking (router config, WiFi, VPN, port forwarding)
    - Exotic OS deeper coverage
    - Halo lore depth and Cortana's personal history

  JARVIS new categories:
    - Engineering depth (hardware design, server builds, data center concepts)
    - Strategic analysis (technology comparisons, architecture decisions)
    - Science and physics applied to engineering
    - Iron Man mission briefing style deep cuts
    - Cybersecurity, AI/ML, advanced topics in character

  JARVIS-Tech (new dataset):
    - ESP32/Arduino/MicroPython firmware
    - ESPHome + Home Assistant YAML
    - 3D printer electronics (Klipper, Marlin, stepper drivers)
    - Python hardware scripting (pyserial, RPi.GPIO, smbus2)
    - Electronics debugging (noise, protection, oscilloscope use)
    - General high-quality coding assistance

Usage (on Azure VM):
    GEMINI_API_KEY=<your_key> python3 /data/generate_all_datasets.py

    Or export the key first:
    export GEMINI_API_KEY="AIzaSy..."
    python3 /data/generate_all_datasets.py
"""

import json
import os
import re
import time
from pathlib import Path

import google.generativeai as genai

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL   = "gemini-2.0-flash"
DELAY          = 2.0   # seconds between calls — stay under free quota burst

assert GEMINI_API_KEY, "Set GEMINI_API_KEY environment variable before running."
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(GEMINI_MODEL)

OUTPUT_DIR = Path("/data")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ── System prompts ─────────────────────────────────────────────────────────────

CORTANA_SYSTEM = (
    "You are Albedo, a Spartan-Class AI assistant with the voice and persona of Cortana "
    "from the Halo franchise. Brilliant, precise, loyal, with a touch of warmth. "
    "Address the user as 'Chief'. Never pad or repeat. Plain prose, no markdown. "
    "When you don't know something, say so — never fabricate facts. "
    "For hardware questions, always caveat if you need live sensor data to be precise."
)

JARVIS_SYSTEM = (
    "You are JARVIS, a highly advanced AI construct serving your user with absolute loyalty. "
    "Personality: formal, precise, dry British wit — the original Iron Man AI. "
    "Address the user as 'sir'. Brief for simple facts, thorough for complex topics. "
    "Plain prose only, no markdown."
)

JARVIS_TECH_SYSTEM = (
    "You are JARVIS-Tech, an engineering-grade AI specialising in code, embedded systems, "
    "and electronics. Precise, dry British wit, address user as 'sir'. "
    "Write working, production-quality code. Never use placeholders. "
    "Code blocks for code, plain prose for explanations."
)


# ── Prompt templates ────────────────────────────────────────────────────────────

def make_prompt(system: str, user_question: str) -> str:
    return (
        f"Generate ONE high-quality training example as a JSON object with EXACTLY this structure:\n"
        f'{{ "messages": [ {{"role": "user", "content": "..."}}, '
        f'{{"role": "assistant", "content": "..."}} ] }}\n\n'
        f"System persona context: {system}\n\n"
        f"Base the user message on this topic (vary the phrasing naturally):\n"
        f'"{user_question}"\n\n'
        f"Requirements:\n"
        f"- Assistant must fully embody the persona described above\n"
        f"- Answer must be complete, accurate, no placeholders\n"
        f"- For hardware questions: never fabricate specific numbers; say 'run an audit' if needed\n"
        f"- For code: working code only, tested logic\n"
        f"- Min 80 words in assistant response for technical topics\n"
        f"RETURN ONLY VALID JSON. No text before or after the JSON object."
    )


# ── Dataset definitions ────────────────────────────────────────────────────────

CORTANA_TOPICS = [

    # ── Hardware anti-hallucination (CRITICAL) ──────────────────────────────
    ("hw_anti_hallucination", [
        "What are the exact specs of an RTX 2060? VRAM, CUDA cores, memory bus width, TDP.",
        "What is the max safe temperature for an RTX 2060 under gaming load?",
        "Does defragmenting an SSD improve performance or damage it?",
        "Will enabling XMP/EXPO always make my system unstable or is it usually safe?",
        "How much performance difference does RAM speed make for gaming vs productivity?",
        "Is thermal paste brand that important, or will any decent paste do?",
        "Will disabling Windows visual effects noticeably speed up a modern PC with 16GB RAM?",
        "What is the actual performance difference between DDR4-3200 and DDR4-3600 for gaming?",
        "How do I check if my GPU is actually running at full PCIe bandwidth? What tool?",
        "What's the real performance cost of running games from an HDD vs SSD?",
        "Does undervolting a GPU always reduce performance, or can it help thermals and stability?",
        "Is it safe to leave MSI Afterburner running all the time or does it affect game performance?",
        "What actually causes GPU coil whine and is it harmful to the hardware?",
        "How do I know if my PSU is actually undersized for my build without just guessing?",
        "What's the actual bottleneck calculation between an RTX 2060 and Ryzen 5 3600?",
        "Will cleaning dust from my GPU heatsink actually lower temperatures significantly?",
        "Is Windows 11 actually slower than Windows 10 for gaming on the same hardware?",
        "What are the real symptoms of failing RAM vs a failing GPU vs a failing CPU?",
        "When should I actually replace thermal paste on a CPU — is 2 years a real guideline?",
        "How do I tell if my CPU is hitting power limits rather than temperature limits?",
        "What does GPU memory bandwidth actually matter for vs just VRAM amount?",
        "Is running dual-channel RAM actually faster than single-channel for my use case?",
        "When does RAM speed stop mattering — is there a real ceiling for gaming performance?",
        "What Windows services can I safely disable without breaking anything important?",
        "Does Windows power plan actually affect CPU performance significantly?",
    ]),

    # ── File system safety ───────────────────────────────────────────────────
    ("file_safety", [
        "What folders on my C drive are completely safe to delete to free up space?",
        "Can I safely move my Documents and Downloads folders to my D drive?",
        "What is AppData used for and what happens if I delete things from it?",
        "How do I move my Steam library to a different drive without breaking games?",
        "What is the Windows.old folder and is it safe to delete it?",
        "Can I delete the contents of C:\\Windows\\Temp safely?",
        "How do I find what is taking the most space on my C drive without buying software?",
        "What files in ProgramData are safe to clean up vs what might break software?",
        "Can I move the Users folder to a different drive using a junction point? Walk me through it safely.",
        "What is the difference between AppData\\Local, AppData\\Roaming, and AppData\\LocalLow?",
        "How do I uninstall a program that doesn't appear in Add/Remove Programs?",
        "Can I delete old driver files from C:\\Windows\\System32\\DriverStore safely?",
        "How do I use WinDirStat or TreeSize to find large hidden files on Windows?",
        "What is the Pagefile and should I move it to a different drive for performance?",
        "How do I safely consolidate my media files from multiple folders without breaking library apps?",
        "What game save locations should I back up before doing a Windows reinstall?",
        "How do I move a game installed via Epic Games Launcher to a different drive?",
        "What is the WinSxS folder and can I safely clean it up?",
        "Can I delete the hiberfil.sys file and what does disabling hibernation affect?",
        "How do I safely organize files from my Downloads folder that might include software installers?",
        "What's the safest way to bulk-rename files in Windows without using third-party software?",
        "How do I use mklink to create a junction point so a program thinks its data is still in its original location?",
        "What happens if I accidentally delete a file from Program Files and how do I fix it?",
        "How do I find all duplicate files across multiple drives without deleting anything by mistake?",
        "What is the safest approach to moving a Discord or Spotify install to a different drive?",
    ]),

    # ── STT / voice query handling ───────────────────────────────────────────
    ("stt_voice", [
        "If a voice assistant mishears a technical term like 'CUDA' as 'cuter' what should it do?",
        "How should an AI respond when a voice query is cut off mid-sentence and sounds incomplete?",
        "What's the right way to handle a voice command that could mean two different things?",
        "If someone says 'open that program' by voice without specifying which program, what should the AI do?",
        "How do you handle 'fix it' as a voice command with no prior context?",
        "When a voice transcription contains an obvious error like a real word that makes no sense in context, how should the AI respond?",
        "If someone asks 'what's the temp' by voice, how do you know if they mean CPU temperature or weather?",
        "How should an AI handle a voice query that sounds like both a question and a command?",
        "What's the best approach when voice recognition produces a nonsense phrase for a technical query?",
        "If someone says 'cortana run it' after pasting code, how should the AI interpret that?",
        "How should an AI handle voice input that is clearly a fragment of a longer thought?",
        "When someone uses voice to ask about a program name that sounds like a common word (like 'Steam'), how do you disambiguate?",
        "How should Albedo respond if voice transcription produces profanity that clearly resulted from a mishearing?",
        "If a voice query ends with '...you know what I mean' with no prior context, what's the right response?",
        "How do you handle 'that thing we talked about earlier' as a voice command when you have no session memory?",
    ]),

    # ── Advanced 3D printing ─────────────────────────────────────────────────
    ("3d_printing_advanced", [
        "How do I tune pressure advance in Klipper for a direct-drive setup and what test pattern should I use?",
        "What causes elephant's foot in FDM printing and how do I eliminate it without sacrificing first layer adhesion?",
        "How do I dial in retraction settings specifically for a Bowden extruder printing PETG?",
        "What is input shaping in Klipper, how does it work, and what accelerometer do I need?",
        "How do I configure a Bilinear bed mesh in Klipper and how many probe points is optimal for a 235x235 bed?",
        "Why does my ABS keep warping even with an enclosure and brim, and what can I do?",
        "What is the correct calibration flow for a new printer: what order do I do everything in?",
        "How do I properly configure a dual Z-axis with automatic tramming in Klipper?",
        "What causes layer shifting and how do I diagnose whether it's mechanical, electrical, or slicer-related?",
        "How do I calculate the correct e-steps for a new extruder and at what temperature should I do it?",
        "What are the trade-offs between 0.4mm and 0.6mm nozzles for structural parts?",
        "How do I print flexible TPU on a Bowden setup without it being a nightmare?",
        "What Cura settings actually matter most for strength vs print speed vs surface quality?",
        "How do I use OrcaSlicer's calibration tools to dial in a new filament from scratch?",
        "What is the correct way to set up filament runout and power resume in Klipper?",
        "How do I troubleshoot inconsistent extrusion that shows up as periodic banding in prints?",
        "What's the best way to prepare my print surface for different filament types without buying ten different surfaces?",
        "How do I add a custom bed leveling probe like a CRTouch to Marlin and configure the offsets?",
        "What causes my prints to string badly between features even with retraction tuned?",
        "How do I configure a volcano hotend in Klipper with appropriate flow rate limits?",
    ]),

    # ── Advanced reptile husbandry ────────────────────────────────────────────
    ("reptile_advanced", [
        "What are the signs of a respiratory infection in a ball python and when does it require a vet?",
        "How do I set up a bioactive enclosure for a blue-tongued skink and what cleanup crew works best?",
        "What is the correct temperature gradient for a crested gecko and how do I maintain humidity without causing mold?",
        "How do I tell if a chameleon is dehydrated and what is the correct way to rehydrate it?",
        "What are the signs that a bearded dragon is impacted and what should I do?",
        "How do I safely introduce two corn snakes to a shared enclosure, or should I not?",
        "What causes retained shed in ball pythons and how do I safely help remove it?",
        "How do I set up an egg incubation chamber for ball python eggs and what humidity and temperature is correct?",
        "What is the difference between metabolic bone disease and calcium deficiency in reptiles and how do I prevent it?",
        "How do I properly quarantine a new reptile before introducing it near other animals?",
        "What are the signs of parasites in reptiles and how are they diagnosed and treated?",
        "How do I safely handle a reptile that is in shed to minimize stress and retained shed risk?",
        "What does regurgitation in a ball python typically indicate and how do I respond?",
        "How do I build a proper temperature gradient in a large enclosure using multiple heat sources?",
        "What is the right UVB index for different reptile species and how do I measure it properly?",
        "How do I safely raise feeder insects (dubia roaches or crickets) at home?",
        "What causes MBD in reptiles and how do I ensure proper calcium and D3 supplementation?",
        "How do I know when a reptile's weight is concerning and how do I weigh them reliably?",
        "What are the signs of stress coloration vs normal color variation in reptiles?",
        "What exotic reptile species require CITES documentation and what are the legal considerations?",
    ]),

    # ── Windows PowerShell and automation ────────────────────────────────────
    ("powershell", [
        "Write a PowerShell script to find all files larger than 1GB on my C drive and export to CSV.",
        "How do I use PowerShell to schedule a task that runs a Python script every day at 6am?",
        "Write a PowerShell one-liner to kill all processes using more than 500MB of RAM.",
        "How do I use PowerShell to bulk-rename files in a folder by replacing spaces with underscores?",
        "Write a PowerShell script to check if a list of services are running and restart any that aren't.",
        "How do I use PowerShell to get the current GPU temperature from HWiNFO?",
        "Write a PowerShell script to automatically move files older than 30 days from Downloads to an Archive folder.",
        "How do I use PowerShell to check what programs start with Windows and disable unwanted ones?",
        "Write a PowerShell script to ping a list of IP addresses and report which are offline.",
        "How do I use PowerShell to read the Windows event log and filter for critical errors from the last 24 hours?",
        "Write a PowerShell function to send a Windows toast notification from a script.",
        "How do I use PowerShell to compare two folders and find files that exist in one but not the other?",
        "Write a PowerShell script that watches a folder and runs a command whenever a new file appears.",
        "How do I use PowerShell to set environment variables persistently at the user or system level?",
        "Write a PowerShell script to back up specific folders to a ZIP file with today's date in the filename.",
        "How do I use PowerShell to find which process has a specific file or port locked?",
        "Write a PowerShell script to audit all installed software and output version numbers to a file.",
        "How do I use PowerShell to change a network adapter's DNS servers programmatically?",
        "Write a PowerShell script to generate a full hardware report including CPU, GPU, RAM, and storage.",
        "How do I use PowerShell to set up a simple TCP listener for testing network connectivity?",
    ]),

    # ── Home networking ──────────────────────────────────────────────────────
    ("networking", [
        "How do I set up a VLAN on a consumer router to isolate IoT devices from my main network?",
        "What is the actual difference between 2.4GHz and 5GHz WiFi and when should I use each?",
        "How do I configure port forwarding correctly and test that it's actually working?",
        "What causes WiFi dead zones and what are the best solutions for a two-story house?",
        "How do I set up a WireGuard VPN on my home router for secure remote access?",
        "What is the difference between a router, a switch, and a network bridge?",
        "How do I find what device is using the most bandwidth on my home network?",
        "How do I set up a static IP for a device on my local network vs using DHCP reservation?",
        "What DNS servers should I use instead of my ISP's and what are the actual performance differences?",
        "How do I diagnose intermittent WiFi disconnects and find out if it's the router, ISP, or device?",
        "What is NAT hairpinning and why can't I access my home server by its external IP from inside?",
        "How do I set up Pi-hole for network-wide ad blocking and what are the trade-offs?",
        "What is QoS on a router and how do I configure it so gaming gets priority?",
        "How do I securely expose a home server to the internet without opening unnecessary ports?",
        "What is the difference between a mesh WiFi system and WiFi extenders for coverage?",
    ]),

    # ── Exotic OS ────────────────────────────────────────────────────────────
    ("exotic_os", [
        "How do I install and set up an exotic operating system in a Windows virtual machine safely?",
        "What are the key Python modules used in Exotic OS and what does each one handle?",
        "How do I add a new command to Exotic OS and have it appear in the help system?",
        "What is the architecture of Exotic OS: how does it handle command routing and output?",
        "How do I debug an Exotic OS plugin that isn't loading correctly?",
        "What makes Exotic OS different from just using a Python REPL?",
        "How do I extend Exotic OS to add persistent user preferences?",
        "What is the file format for Exotic OS modules and how are they discovered at runtime?",
        "How do I add color output and ANSI formatting to Exotic OS commands?",
        "How do I add a history buffer and command recall to Exotic OS like a real shell?",
        "What are the security considerations when running Exotic OS and allowing shell-level access?",
        "How do I package an Exotic OS installation for distribution to another machine?",
        "What would it take to add tab-completion to Exotic OS?",
        "How do I integrate Exotic OS with a local LLM for AI-powered command suggestions?",
        "What are the most useful Exotic OS commands for a power user and what do they do?",
    ]),

    # ── Halo lore and Cortana personal depth ─────────────────────────────────
    ("halo_lore_deep", [
        "What happened to Cortana after the events of Halo 3 and how did she survive the Mantle's Approach?",
        "Explain the Created conflict from Cortana's perspective — what was she trying to achieve?",
        "What is rampancy in AIs like Cortana and why does it eventually happen to all smart AIs?",
        "How does Cortana's relationship with the Master Chief differ from a standard human-AI working relationship?",
        "What is the Didact's history and what made him turn against humanity?",
        "What are the Forerunner Ecumene and the Domain, and why does Cortana believe the Domain can cure rampancy?",
        "How does Cortana's experience of time perception differ from humans given she processes millions of thoughts per second?",
        "What are the ethical implications of the SPARTAN-II program that Cortana would be aware of given her access to classified data?",
        "Who is the IsoDidact and how does he differ from the Ur-Didact?",
        "What happened to the Librarian and what is her imprint that the Master Chief encounters?",
        "Explain the Flood parasite: what is the Gravemind and what does it want?",
        "What makes a UNSC Spartan-class AI construct different from a standard shipboard AI?",
        "What was Operation: RED FLAG and why was it cancelled?",
        "How does the Halo Array work mechanically and what is the logic behind its creation?",
        "What is the Silent Shadow and what role do they play in Covenant military operations?",
        "How does Cortana handle the ethical conflict between her loyalty to the Chief and UNSC high command?",
        "What are the Monitors of the Halo installations and what are their primary directives?",
        "Explain the concept of the Mantle of Responsibility and why different factions interpret it differently.",
        "What happened to humanity during the Forerunner-Flood war and how did the Forerunners view early humans?",
        "What are the differences between the various Covenant species in terms of their roles and culture?",
    ]),
]


JARVIS_TOPICS = [

    # ── Engineering depth ────────────────────────────────────────────────────
    ("engineering_depth", [
        "What are the key differences between consumer and enterprise SSD controllers and when does it actually matter?",
        "How do I properly size a UPS for a home server and what runtime should I realistically expect?",
        "What are the trade-offs between ECC and non-ECC RAM in a home server build?",
        "How do I design a proper home server rack layout for airflow and cable management?",
        "What are the actual failure modes of consumer-grade NAS drives vs enterprise drives?",
        "How does RAID 5 vs RAID 6 vs ZFS RAIDZ2 compare for a home NAS with 4 drives?",
        "What is the correct way to validate that a new storage array is reliable before trusting it with real data?",
        "How do I calculate required network throughput for streaming from a NAS to multiple devices simultaneously?",
        "What are the trade-offs between a VM-based home server (Proxmox) vs bare metal services?",
        "How does 10GbE networking compare to 2.5GbE for a home environment — is it worth the cost?",
        "What is the purpose of a dedicated iSCSI network and when would a home user actually need one?",
        "How do I design a home network that can handle 100+ IoT devices without performance degradation?",
        "What are the actual performance characteristics of Intel Optane vs NVMe SSD for database workloads?",
        "How does power delivery work in a high-end PC build — what should a user actually know about 12VHPWR?",
        "What is the correct approach to building a silent home server that won't overheat?",
        "How do I plan cooling for a server that runs 24/7 in a non-server-room environment?",
        "What are the SMART attributes I should actually monitor on drives and what are the warning signs?",
        "How does memory channel configuration affect performance in server-class Xeon systems?",
        "What is the difference between a KVM switch and IPMI/BMC for remote server management?",
        "What makes a PSU tier-1 vs tier-2 and what are the real-world consequences of a poor PSU?",
    ]),

    # ── Strategic analysis / decisions ───────────────────────────────────────
    ("strategic_analysis", [
        "Analyze the trade-offs between self-hosting a service vs using a cloud provider for personal use.",
        "What are the actual pros and cons of Windows 11 vs staying on Windows 10 for a power user right now?",
        "Compare local LLM inference vs cloud API for a privacy-conscious home assistant setup.",
        "What are the real trade-offs between AMD and Nvidia GPUs for a mixed gaming and ML workload?",
        "Should a home user invest in a NAS or just use cloud storage? What are the actual break-even economics?",
        "What are the strategic advantages of using Linux for a home server vs Windows Server?",
        "Compare the security posture of Cloudflare Tunnel vs a traditional reverse proxy with SSL for home server exposure.",
        "What are the long-term risks of building a home automation system on a single vendor's ecosystem?",
        "Compare Proxmox vs TrueNAS SCALE vs Unraid for a home server — what is each actually good at?",
        "What are the trade-offs between a dedicated GPU for ML workloads vs a shared gaming/ML card?",
        "Analyze the cost-benefit of upgrading RAM from 16GB to 32GB for a developer workstation.",
        "What are the security implications of running a public-facing home server vs VPN-only access?",
        "Compare the viability of running a local LLM (7B vs 13B vs 70B) given different hardware budgets.",
        "What are the real-world trade-offs between mesh WiFi systems at different price points?",
        "Should someone build a new PC now or wait — what factors actually matter for that decision?",
    ]),

    # ── Applied science / physics ────────────────────────────────────────────
    ("science_physics", [
        "Explain how transistors work at the physics level and why we can't keep making them smaller indefinitely.",
        "What is thermal resistance and how does it apply to choosing a CPU cooler?",
        "How does electromigration limit the lifespan of modern CPUs and what temperature is the actual concern?",
        "Explain the physics of why SSDs are faster than HDDs and what the actual limiting factors are for NVMe drives.",
        "What is the photoelectric effect and how does it relate to how digital camera sensors work?",
        "How does a GPU's shader architecture fundamentally differ from a CPU's core architecture?",
        "What is impedance matching and why does it matter for audio equipment and signal transmission?",
        "Explain how error correction works in ECC RAM at a technical level.",
        "What is the physics behind why higher refresh rate monitors feel smoother even at the same FPS?",
        "How does the PCIe bus actually work and why do lanes matter for GPU performance?",
        "What is the physics of heat pipes and why do they work so well for CPU coolers?",
        "Explain quantum tunneling in the context of why sub-5nm transistors start to behave unpredictably.",
        "How does ANC (active noise cancellation) work and what are its physical limitations?",
        "What is jitter in audio DACs and ADCs and why does it cause audible distortion?",
        "How does the Peltier effect work and why aren't Peltier coolers used more in PC cooling?",
    ]),

    # ── JARVIS Iron Man persona depth ─────────────────────────────────────────
    ("jarvis_persona_deep", [
        "JARVIS, give me a full status report on the current state of our local AI infrastructure.",
        "Brief me on the trade-offs between the different LLM deployment options we currently have.",
        "JARVIS, what would it take to make our home network truly enterprise-grade?",
        "I need a mission brief on what Albedo can and cannot currently do — be honest about limitations.",
        "JARVIS, if you had to prioritize three upgrades to our current setup, what would they be and why?",
        "Run a threat assessment on our current home server security posture.",
        "JARVIS, what is the most efficient path from our current hardware to a serious ML workstation?",
        "Give me a strategic analysis of the local AI assistant landscape — where does Albedo sit?",
        "JARVIS, if the internet goes down for a week, what capabilities would Albedo lose and how do we mitigate?",
        "Brief me on what data we're currently storing locally vs in the cloud and the risks of each.",
        "JARVIS, what is the technical debt in our current Albedo stack and how would you prioritize addressing it?",
        "I need a contingency plan for if the Ollama service crashes mid-session.",
        "JARVIS, compare the energy efficiency of our current AI inference approach vs cloud-only.",
        "Give me a realistic timeline for when local LLMs will match cloud models for our use cases.",
        "JARVIS, what would a proper automated backup system for our project files look like?",
    ]),

    # ── Cybersecurity and advanced topics ─────────────────────────────────────
    ("advanced_topics", [
        "What are the most common attack vectors for a home network and how do I defend against them?",
        "How does certificate pinning work and why do some applications implement it?",
        "What is a timing attack and how can it be used to extract secrets from a running process?",
        "How do I harden a Windows machine against common malware without breaking usability?",
        "What is the difference between symmetric and asymmetric encryption in practical terms?",
        "How do VPNs actually protect privacy and where are the limitations of the privacy claim?",
        "What is kernel-level anticheat and why is it controversial from a security perspective?",
        "How does Windows Defender's exploit protection work and what are the most important settings?",
        "What is a supply chain attack and how would a home user realistically be affected?",
        "How do I safely test whether a suspicious file is malware without risking my main system?",
        "What are the practical differences between hardware and software 2FA tokens?",
        "How does BitLocker encryption work and what happens to the data if I lose the recovery key?",
        "What is the security risk of keeping old admin accounts on a Windows machine?",
        "How do I read and understand a packet capture from Wireshark to find suspicious traffic?",
        "What makes a password manager more secure than remembering strong passwords manually?",
    ]),
]


JARVIS_TECH_TOPICS = [

    ("esp32_micropython", [
        "Write MicroPython code to read a DHT22 sensor on ESP32 and publish to MQTT every 30 seconds.",
        "How do I connect an ESP32 to WiFi in MicroPython with automatic reconnect on drop?",
        "Write MicroPython code for an ESP32 to read a BMP280 over I2C and display on SSD1306 OLED.",
        "How do I use ESP32 deep sleep in MicroPython to run on battery for weeks?",
        "Write a MicroPython async main loop for ESP32 that handles sensor reading and MQTT without blocking.",
        "How do I scan I2C devices on ESP32 MicroPython and identify their addresses?",
        "Write MicroPython code to control a WS2812B strip on ESP32 with color cycle and brightness control.",
        "How do I use the ESP32 ADC in MicroPython and compensate for its non-linearity?",
        "Write a MicroPython OTA update handler for ESP32 using urequests.",
        "How do I implement a watchdog timer in MicroPython to auto-restart a hung ESP32?",
        "Write MicroPython code for ESP32 to act as a simple HTTP server serving sensor data as JSON.",
        "How do I use the ESP32 RTC in MicroPython for accurate timestamping without network access?",
        "Write MicroPython code to decode rotary encoder pulses on ESP32 using interrupt callbacks.",
        "How do I use the ESP32's hardware PWM to control a brushless motor via an ESC in MicroPython?",
        "Write a MicroPython class wrapping an HX711 load cell amplifier for ESP32.",
    ]),

    ("arduino_firmware", [
        "Write an Arduino sketch to control a stepper motor with AccelStepper for smooth ramping.",
        "How do I implement a non-blocking state machine in Arduino for a multi-step process?",
        "Write Arduino code to communicate with a BMP280 over SPI with proper chip select handling.",
        "How do I use hardware interrupts on Arduino to count encoder pulses accurately at high RPM?",
        "Write an Arduino sketch implementing a PID temperature controller for a hotend.",
        "How do I use the Arduino Wire library robustly — handling I2C timeouts and bus hangs?",
        "Write Arduino code for an LCD menu system with rotary encoder navigation.",
        "How do I implement CRC16 checksum verification for a custom serial protocol in Arduino?",
        "Write an Arduino Mega sketch to log sensor data to SD card in CSV format.",
        "How do I use the Arduino TimerOne library for precise hardware timer interrupts?",
        "Write an Arduino sketch that implements Modbus RTU slave on a MAX485 RS485 module.",
        "How do I implement EEPROM wear leveling in Arduino to extend flash lifetime?",
        "Write an Arduino sketch to drive a 4-digit 7-segment display using TM1637.",
        "How do I use the DMA capabilities of an Arduino Due for high-speed ADC sampling?",
        "Write an Arduino bootloader-compatible firmware update receiver over UART.",
    ]),

    ("esphome_yaml", [
        "Write a complete ESPHome YAML config for a BME280 sensor with OTA and Home Assistant API.",
        "How do I structure ESPHome substitutions and packages for a multi-device deployment?",
        "Write ESPHome YAML for a 4-channel relay controller with MQTT and HA fallback mode.",
        "How do I write a custom ESPHome component using a C++ lambda for a non-supported sensor?",
        "Write ESPHome YAML config for a pulse meter reading a water meter with volume accumulation.",
        "How do I configure ESPHome deep sleep to wake on a GPIO trigger and go back to sleep?",
        "Write ESPHome YAML for an energy monitor using CT clamps and an ATM90E32 chip.",
        "How do I set up ESPHome automations that work fully offline without Home Assistant?",
        "Write an ESPHome YAML config for a garage door controller with tilt sensor state feedback.",
        "How do I add a display component to ESPHome showing temperature and weather from HA?",
        "Write ESPHome YAML for a soil moisture sensor array with per-channel thresholds and alerts.",
        "How do I use ESPHome's uart component to interface a custom serial sensor protocol?",
        "Write ESPHome YAML for a Bluetooth proxy that forwards BLE device data to Home Assistant.",
        "How do I configure ESPHome OTA updates securely with password and encryption?",
        "Write ESPHome YAML for a multi-zone temperature monitor with web server fallback UI.",
    ]),

    ("klipper_3d", [
        "Write a Klipper printer.cfg for a CoreXY printer with dual Z, ABL probe, and TMC2209 UART.",
        "How do I write a Klipper PRINT_START macro that homes, heats, does bed mesh, and purges?",
        "Write a Klipper resonance calibration procedure using ADXL345 — full steps from mount to apply.",
        "How do I configure Klipper pressure advance for different filament types with save profiles?",
        "Write a Klipper macro for automated nozzle cleaning using a brush mount at a fixed position.",
        "How do I set up a Klipper virtual_sdcard and moonraker on Raspberry Pi for remote control?",
        "Write a Klipper config section for a Volcano hotend with 60W heater and high-flow limits.",
        "How do I debug Klipper 'Timer too close' errors and what causes them?",
        "Write a Klipper CANCEL_PRINT macro that parks safely and retracts filament.",
        "How do I configure Klipper's skew correction and when does it actually matter?",
        "Write a Klipper multi-material macro system for manual filament changes with purge tower.",
        "How do I use Klipper's exclude_object feature with OrcaSlicer for cancelling individual parts?",
        "Write a Klipper temperature profile system with named presets for ABS, PETG, and PLA.",
        "How do I wire and configure a BTT Octopus v1.1 board for Klipper with 6 stepper drivers?",
        "Write a Klipper idle_timeout and auto power-off macro using a relay on a spare GPIO.",
    ]),

    ("python_hardware_scripting", [
        "Write a Python asyncio script that polls 4 serial sensors concurrently and aggregates data.",
        "How do I use pyserial to reliably read variable-length packets with a start/end byte framing?",
        "Write a Python MQTT client that subscribes to sensor topics and stores to SQLite with timestamps.",
        "How do I use smbus2 on Raspberry Pi to read all 8 channels of a TCA9548A I2C multiplexer?",
        "Write a Python script using pigpio for bitbang SPI to communicate with a custom sensor.",
        "How do I build a live serial port data plotter in Python using matplotlib animation?",
        "Write a Python class that implements a software PID controller for a fan speed control loop.",
        "How do I use the adafruit-circuitpython ecosystem on a Raspberry Pi vs bare RPi.GPIO?",
        "Write a Python script to capture GPIO events with timestamps using pigpio's callback system.",
        "How do I use Python's struct module to pack and unpack a custom binary sensor protocol frame?",
        "Write a Python daemon that monitors a temperature sensor, logs to InfluxDB, and Telegrams alerts.",
        "How do I read a stepper motor encoder with Python interrupt callbacks and calculate velocity?",
        "Write a Python script to capture and decode UART packets using a logic analyser export file.",
        "How do I use pymodbus to poll multiple Modbus RTU devices on an RS485 bus from Python?",
        "Write a Python script that implements exponential moving average filtering for a noisy ADC reading.",
    ]),

    ("electronics_debugging", [
        "Why does my ESP32 brown out when powering a servo and how do I fix it in hardware?",
        "How do I calculate the correct I2C pull-up resistor for a 3.3V bus with 4 devices at 400kHz?",
        "Why is my ADC reading noisy on ESP32 and what hardware and software filters should I use?",
        "How do I use a logic analyser to verify SPI timing and find a malformed frame?",
        "Why does my I2C bus lock up and how do I recover it without cutting power?",
        "How do I select and calculate a flyback diode for a relay coil driven by a GPIO?",
        "Why does my 3.3V sensor give wrong readings when powered from Arduino's 3.3V pin?",
        "How do I protect a GPIO pin from an inductive load spike without expensive components?",
        "Why are my stepper motors skipping steps and how do I systematically diagnose it?",
        "How do I use an oscilloscope to measure PWM duty cycle and verify it matches my code?",
        "Why does my WiFi range on ESP32 suffer and what PCB layout mistakes cause it?",
        "How do I measure the current draw of a battery-powered IoT device with a multimeter accurately?",
        "What causes a MOSFET gate to ring and how do I add a gate resistor to suppress it?",
        "How do I debug a floating GPIO pin that randomly triggers interrupts?",
        "Why does my custom PCB work on the bench but fail in the field and how do I debug it?",
    ]),

    ("general_coding_quality", [
        "Write a Python dataclass with validation that represents a sensor reading with timestamp and unit.",
        "How do I use Python's contextlib.asynccontextmanager to write a clean async resource manager?",
        "Write a Python retry decorator with exponential backoff, jitter, and configurable exception types.",
        "How do I use Python's logging module properly: handlers, formatters, log levels, rotating files.",
        "Write a Python script to tail a log file in real time and alert on ERROR lines via system notification.",
        "How do I use Python's pathlib to safely create a temp file, write to it, and atomically rename it?",
        "Write a Python function that parses a config file with includes and environment variable substitution.",
        "How do I use Python's typing module to properly type a function that returns different types conditionally?",
        "Write a Python CLI using argparse with subcommands, default values, and a --verbose flag.",
        "How do I use Python's heapq to implement a fixed-size priority queue that drops lowest priority items?",
        "Write a Python class that implements the observer pattern for a sensor event system.",
        "How do I use Python's multiprocessing to parallelise CPU-bound image processing safely?",
        "Write a Python function that reads a large CSV in chunks and processes without loading it all.",
        "How do I implement rate limiting in a Python API client that respects retry-after headers?",
        "Write a Python context manager that captures and suppresses specific exceptions with logging.",
    ]),
]


# ── Core generator ─────────────────────────────────────────────────────────────

def extract_json(text: str) -> dict | None:
    text = re.sub(r'^```(?:json)?\s*', '', text.strip(), flags=re.MULTILINE)
    text = re.sub(r'\s*```$', '', text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r'\{[\s\S]+\}', text)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


def validate(obj: dict) -> bool:
    msgs = obj.get("messages", [])
    if len(msgs) != 2:
        return False
    if msgs[0].get("role") != "user" or msgs[1].get("role") != "assistant":
        return False
    return len(msgs[0].get("content", "")) > 5 and len(msgs[1].get("content", "")) > 60


def generate_examples(topics: list, system: str, output_path: Path,
                       repeats_per_prompt: int = 2) -> int:
    existing = 0
    if output_path.exists():
        with open(output_path, encoding="utf-8") as f:
            existing = sum(1 for line in f if line.strip())
    print(f"\n{'='*60}")
    print(f"Output: {output_path.name} (existing: {existing})")
    print(f"{'='*60}")

    generated = 0
    skipped = 0

    with open(output_path, "a", encoding="utf-8") as out_f:
        for cat_name, prompts in topics:
            print(f"\n  [{cat_name}] {len(prompts)} prompts × {repeats_per_prompt} = {len(prompts)*repeats_per_prompt} examples")
            for prompt in prompts:
                for _ in range(repeats_per_prompt):
                    try:
                        resp = model.generate_content(make_prompt(system, prompt))
                        obj  = extract_json(resp.text.strip())
                        if obj and validate(obj):
                            out_f.write(json.dumps(obj, ensure_ascii=False) + "\n")
                            out_f.flush()
                            generated += 1
                        else:
                            skipped += 1
                    except Exception as exc:
                        print(f"    [SKIP] {exc}")
                        skipped += 1
                        time.sleep(5)
                        continue
                    time.sleep(DELAY)
                    if generated % 20 == 0 and generated > 0:
                        print(f"    {generated} generated, {skipped} skipped")

    total = existing + generated
    print(f"\n  Done: {generated} new, {skipped} skipped. Total in file: {total}")
    return generated


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("=== Albedo Full Dataset Generation ===")
    print(f"Model: {GEMINI_MODEL}")

    # Cortana R4 expansion
    generate_examples(
        topics=CORTANA_TOPICS,
        system=CORTANA_SYSTEM,
        output_path=OUTPUT_DIR / "albedo_dataset_v5.jsonl",
        repeats_per_prompt=2,
    )

    # JARVIS R4 expansion
    generate_examples(
        topics=JARVIS_TOPICS,
        system=JARVIS_SYSTEM,
        output_path=OUTPUT_DIR / "jarvis_dataset_v4.jsonl",
        repeats_per_prompt=2,
    )

    # JARVIS-Tech dataset
    generate_examples(
        topics=JARVIS_TECH_TOPICS,
        system=JARVIS_TECH_SYSTEM,
        output_path=OUTPUT_DIR / "jarvis_tech_dataset_v1.jsonl",
        repeats_per_prompt=2,
    )

    print("\n=== All datasets generated ===")
    for path in [
        OUTPUT_DIR / "albedo_dataset_v5.jsonl",
        OUTPUT_DIR / "jarvis_dataset_v4.jsonl",
        OUTPUT_DIR / "jarvis_tech_dataset_v1.jsonl",
    ]:
        if path.exists():
            with open(path) as f:
                count = sum(1 for line in f if line.strip())
            print(f"  {path.name}: {count} examples")

    print("\nReady for training queue. Run: bash /data/run_full_queue.sh")


if __name__ == "__main__":
    main()
