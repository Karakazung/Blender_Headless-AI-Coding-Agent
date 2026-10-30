# Blender Headless AI Coding Agent (Automation Suite)

ชุดเครื่องมือและสถาปัตยกรรมอัตโนมัติสำหรับการรัน **Blender แบบ Headless (Background Mode)** ควบคุมผ่าน Command Line และ Python BPY Script ออกแบบมาสำหรับ AI Coding Agent และ Automated Workflows โดยเฉพาะ

---

## 🚀 คุณสมบัติเด่น (Key Features)

- **Pure Headless Execution**: รันสคริปต์ 3D เบื้องหลัง 100% โดยไม่ต้องเปิดหน้าต่าง GUI
- **Blender Path Resolution Protocol**: ค้นหาพาธของ `blender.exe` อัตโนมัติ 6 ระดับ (Cache, ENV, PATH, Registry, Common Drives) ไม่ต้องฮาร์ดโค้ดพาธ
- **Scene Package Structure**: สถาปัตยกรรมแยกส่วนประกอบ 7 มิติ (`build`, `config`, `materials`, `geometry`, `layout`, `assertions`, `inspect`)
- **Deterministic 5-Pillar Quality Audits**:
  1. `audit_interpenetration()`: ตรวจจับ Bounding Box (AABB Fast-path) และคัดกรองการซ้อนทับระดับโพลีกอนด้วย BVHTree พร้อมรองรับ `mark_assembly_mate()`
  2. `audit_floating()`: ตรวจจับวัตถุลอยในสุญญากาศ หรือจมดินลึกเกินพิกัดความเผื่อด้วย Multi-point Raycasting
  3. `audit_attachment_contact()`: วัดระยะห่างผิวสัมผัส (Surface-gap check) สำหรับชิ้นส่วนติดผนัง (`mark_side_attached`) หรือข้อต่อสวมแกน (`mark_joint_attached`)
  4. `audit_spacing()`: ตรวจจับระยะห่างในแถวหรืออาเรย์ที่ตำแหน่งคลาดเคลื่อน (Pattern & Array Drift) พร้อมคำนวณ Adaptive Tolerance
  5. `audit_exposure()`: ตรวจวัดค่าความสว่างเฉลี่ย (Mean/Median Luma), อัตราส่วนจุดแสงตัดยอด (Specular Clipping >= 250), พื้นที่มืดสนิท (Crushed Blacks <= 15), และ Hotspot Drift ในฉากกลางคืน
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
│   └── quality_checker.py      # โมดูลตรวจวัดค่า Luma และเรขาคณิต 5 เสาหลัก
├── tests/
│   └── test_headless_smoke.py  # ชุดทดสอบ Unit & Smoke Test (12 checks)
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

### 3. รันชุดทดสอบคุณภาพ (Smoke & Unit Tests)
```powershell
python tests/test_headless_smoke.py
```

---

## 📜 มาตรฐานค่าความสว่างแสง (Calibrated Exposure Bands)
อ้างอิงตามข้อกำหนด **Capybala BPY §10.2**:
- **สตูดิโอ (Studio)**: Mean Luma `100 – 170`, Max Clipping `<= 1.5%`, Max Dark `<= 35.0%`
- **กลางแจ้งแสงสีทอง (Outdoor Golden)**: Mean Luma `95 – 175`, Max Clipping `<= 2.0%`, Max Dark `<= 30.0%`
- **กลางคืน (Night)**: Mean Luma `15 – 70`, Max Clipping `<= 2.5%`, Max Dark `<= 55.0%`, `|Mean - Median| <= 18.0`
- **อวกาศ (Space)**: Mean Luma `5 – 60`, Max Clipping `<= 1.5%`, Max Dark `<= 92.0%`
