@echo off
cd /d C:\Users\kawak\line-quiz-bot
python extract_problems.py --append --grade 中学2年 >> extract_log_grade2.txt 2>&1
