@echo off
cd /d C:\Users\kawak\line-quiz-bot
python extract_social_problems.py --append --grade_range 2年1学期前半 --grade_range 2年1学期後半 >> extract_log_social_day2.txt 2>&1
