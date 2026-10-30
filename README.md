# Blender Headless AI Coding Agent (Automation Suite)

ชุดเครื่องมือและสถาปัตยกรรมอัตโนมัติสำหรับการรัน **Blender แบบ Headless (Background Mode)** ควบคุมผ่าน Command Line และ Python BPY Script ออกแบบมาสำหรับ AI Coding Agent และ Automated Workflows โดยเฉพาะ

---

## 🚀 คุณสมบัติเด่น (Key Features)

- **Pure Headless Execution**: รันสคริปต์ 3D เบื้องหลัง 100% โดยไม่ต้องเปิดหน้าต่าง GUI
- **Blender Path Resolution Protocol**: ค้นหาพาธของ `blender.exe` อัตโนมัติ 6 ระดับ (Cache, ENV, PATH, Registry, Common Drives) ไม่ต้องฮาร์ดโค้ดพาธ
- **Scene Package Structure**: สถาปัตยกรรมแยกส่วนประกอบ 7 มิติ (`build`, `config`, `materials`, `geometry`, `layout`, `assertions`, `inspect`)
- **Deterministic Quality Audits**: ตรวจสอบการชนกันของวัตถุ (Interpenetration), วัตถุลอย (Floating), และค่าความสว่างแสง (Calibrated Luma Bands) ก่อนส่งมอบ
- **Production GLB Export**: ส่งออกโมเดลเกมและแอปพลิเคชัน 3D พร้อมเซ็ต Origin / Pivot Point ที่ฐานล่างกึ่งกลาง `(0, 0, 0)`

---

## 🛠️ โครงสร้างโปรเจกต์ (Project Structure)

```text
Blender_Headless-AI-Coding-Agent/
├── scripts/
│   ├── find_blender.ps1        # สคริปต์ค้นหาพาธ blender.exe อัตโนมัติ
│   ├── run_headless.ps1        # สคริปต์รันคำสั่ง Headless CLI มาตรฐาน
│   └── template_worker.py      # ตัวอย่าง BPY Worker สคริปต์
├── src/
│   ├── scene_builder.py        # โมดูลสร้างและประกอบฉาก 3D
│   └── quality_checker.py      # โมดูลตรวจวัดค่า Luma และเรขาคณิต
├── tests/
│   └── test_headless_smoke.py  # ชุดทดสอบความพร้อมของระบบ (Smoke Test)
├── .gitignore
└── README.md
```

---

## 💻 การใช้งานเบื้องต้น (Quick Start)

### 1. ตรวจสอบความพร้อมของ Blender (Preflight Check)
```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_headless.ps1 --probe
```

### 2. รันสคริปต์สร้างโมเดลและเรนเดอร์แบบเบื้องหลัง
```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_headless.ps1 -Script scripts/template_worker.py
```

---

## 📜 ข้อกำหนดมาตรฐานวิศวกรรม (Engineering Standards)
อ้างอิงและพัฒนาต่อยอดตามกฎบัตร **Universal Agent & Skills Architecture** ของ Project Rotusz:
- Cycles GPU/CPU thread safety cap: `threads=6`
- Zero Z-fighting & Non-manifold geometric guarantees
- Calibrated exposure bands (Studio: 100–170, Outdoor: 95–175, Night: 15–70)
