@echo off
cd /d C:\Users\kawak\line-quiz-bot
python extract_social_problems.py --append --grade_range 2年2学期 --grade_range 2年3学期 >> extract_log_social_day3.txt 2>&1
