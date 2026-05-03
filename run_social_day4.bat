@echo off
cd /d C:\Users\kawak\line-quiz-bot
python extract_social_problems.py --append --grade_range 3年1学期 >> extract_log_social_day4.txt 2>&1
