@echo off
cd /d C:\Users\kawak\line-quiz-bot
python extract_social_problems.py --append --grade_range 3年2学期後半 --grade_range 3年3学期 >> extract_log_social_day6.txt 2>&1
