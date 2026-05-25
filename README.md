# University Timetable Scheduler

A web-based automated timetable generation system for university departments using Constraint Satisfaction Problem (CSP) and DFS Backtracking techniques. The system generates conflict-free timetables while considering faculty availability, laboratory scheduling, recourse constraints, and semester-wise academic requirements.

🔗 [University Timetable Scheduler](https://timetable-schedular-gv6c.onrender.com/)

---

## Project Information

### Developed By
- **Shyam Manohar Gupta**
- **Dev Raghuwanshi**

### Guided By
- **Dr. Arun Kumar Das**

**School of Computer and Information Sciences (SCIS)**  
**University of Hyderabad**

---

## Overview

Preparing academic timetables manually is a complex and time-consuming task due to numerous scheduling constraints. This project automates the timetable generation process using Constraint Satisfaction Problem (CSP) techniques and DFS Backtracking.

The system supports multiple academic programs, faculty availability management, laboratory scheduling, recourse handling, and exportable timetable generation through a user-friendly web interface.

---

## Screenshots
<img width="1119" height="660" alt="Screenshot 2026-05-25 at 12 29 58" src="https://github.com/user-attachments/assets/0651bbef-e2fb-4e57-ab5a-f00916f3067e" />
<img width="1123" height="745" alt="Screenshot 2026-05-25 at 12 30 42" src="https://github.com/user-attachments/assets/deef717b-0c39-4967-9b74-e11ae0c1271e" />
<img width="1063" height="328" alt="Screenshot 2026-05-25 at 12 31 47" src="https://github.com/user-attachments/assets/a58b9c3b-b7a6-476a-9c81-e9dc9edb90a4" />
<img width="1470" height="956" alt="Screenshot 2026-05-25 at 12 32 18" src="https://github.com/user-attachments/assets/0efcbf63-456b-4cd8-8c24-2e448a395d8d" />

---

## Objectives

- Automate university timetable generation.
- Reduce manual scheduling effort.
- Prevent faculty and student timetable conflicts.
- Efficiently schedule laboratory sessions.
- Support multiple academic programs and semesters.
- Generate timetable reports in multiple formats.

---

## Features

- Automated timetable generation
- Multi-program support (MCA, M.Tech, IMTech)
- Faculty availability constraints
- Laboratory scheduling support
- Recourse subject management
- Constraint-based conflict detection
- Interactive web interface
- CSV, HTML, PDF, and JSON exports
- Semester-wise and combined timetable views

---

## Technology Stack

### Backend
- Python
- FastAPI

### Frontend
- HTML
- CSS
- JavaScript

### Scheduling Techniques
- Constraint Satisfaction Problem (CSP)
- DFS Backtracking
- Heuristic-Based Search

---

## Project Structure

```text
timetable_scheduler/
├── timetable_scheduler/
│   └── engine/
│       ├── constants.py
│       ├── constraint_utils.py
│       ├── constraints.py
│       ├── export.py
│       ├── models.py
│       ├── parser.py
│       ├── pipeline.py
│       ├── renderer.py
│       ├── scheduler.py
│       └── validator.py
│
├── webui/
│   ├── static/
│   ├── app.py
│   ├── index.html
│   └── start_webui.sh
│
├── requirements.txt
└── README.md
```

---

## System Architecture

The project follows a three-layer architecture:

### User Interface Layer
- HTML, CSS, and JavaScript based web interface
- User input and timetable visualization

### Application Layer
- FastAPI backend
- Handles requests, validation, and timetable generation

### Scheduling Engine Layer
- CSP-based scheduling engine
- DFS Backtracking solver
- Constraint validation and timetable rendering

---

## Scheduling Workflow

1. Input semester and subject information.
2. Configure faculty assignments and availability.
3. Convert subjects into scheduling blocks.
4. Apply academic and scheduling constraints.
5. Generate timetable using DFS Backtracking.
6. Validate generated schedule.
7. Display and export timetable.

---

## Constraints Considered

The scheduler ensures:

- No faculty double-booking
- No semester timetable clashes
- Faculty availability compliance
- Laboratory scheduling rules
- Subject repetition restrictions
- Recourse scheduling constraints
- Day and period boundary validation

---

## Installation

### Clone Repository

```bash
git clone https://github.com/your-username/timetable_scheduler.git
cd timetable_scheduler
```

### Create Virtual Environment

```bash
python -m venv venv
```

### Activate Environment

**Windows**

```bash
venv\Scripts\activate
```

**Linux/macOS**

```bash
source venv/bin/activate
```

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Run Application

```bash
python -m uvicorn webui.app:app --reload
```

Open:

```text
http://localhost:8000
```

---

## Usage

1. Select the semester cycle.
2. Add subjects and faculty information.
3. Configure faculty availability.
4. Add laboratory courses.
5. Generate the timetable.
6. Review generated schedules.
7. Export timetable in the desired format.

---

## Output Formats

The system supports:

- CSV Export
- HTML Export
- PDF Export
- JSON Export

Generated outputs include:

- Semester-wise timetables
- Combined timetable view
- Downloadable reports

---

## Limitations

- Classroom allocation is not implemented.
- Elective scheduling is limited.
- Authentication and user management are not available.
- Very dense constraints may require multiple scheduling attempts.

---

## Future Enhancements

- Classroom allocation module
- Automated elective scheduling
- Database integration
- Faculty-wise timetable view
- User authentication system
- Advanced optimization algorithms
- Analytics and reporting dashboard

---

## Research Foundation

This project was developed after studying and analyzing various research papers related to:

- University Timetable Scheduling
- Graph Coloring Techniques
- Constraint Satisfaction Problems (CSP)
- Automated Academic Scheduling Systems

The reference papers are included in the **Research Papers** directory.

---

## Acknowledgement

We express our sincere gratitude to **Dr. Arun Kumar Das** for his valuable guidance, support, and encouragement throughout the development of this project.

We also thank the **School of Computer and Information Sciences (SCIS), University of Hyderabad**, for providing the opportunity and resources necessary for the successful completion of this work.

---

## License

This project was developed for academic and educational purposes as part of the MCA program at the University of Hyderabad.
