@echo off
cd /d C:\Users\kawak\line-quiz-bot
python extract_problems.py --append --grade 中学3年 >> extract_log_grade3.txt 2>&1
