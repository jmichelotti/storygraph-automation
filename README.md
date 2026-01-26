# StoryGraph Automation

A Python automation tool that syncs reading and listening activity from **Kindle** and **Audible** into **StoryGraph**.

This project is designed for personal use and experimentation, with a focus on reliability, debuggability, and extensibility as Amazon and StoryGraph interfaces evolve.

---

## Features

- 🎧 Fetches Audible library data
- 🔁 Normalizes data across platforms
- 📈 Uploads and updates books on StoryGraph

---

## Project Structure

```
STORYGRAPHAUTOMATION/
├── audible/        # Audible scraping & data extraction
├── kindle/         # Kindle scraping logic (Playwright)
├── storygraph/     # StoryGraph upload & API logic
├── logs/           # Runtime logs (gitignored)
├── runner.py       # Main entry point
└── README.md
```