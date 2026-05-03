$workdir = 'C:\Users\kawak\line-quiz-bot'

$action2 = New-ScheduledTaskAction -Execute "$workdir\run_grade2.bat"
$trigger2 = New-ScheduledTaskTrigger -Once -At '2026-05-04T10:00:00'
Register-ScheduledTask -TaskName 'QuizBot_grade2' -Action $action2 -Trigger $trigger2 -Force

$action3 = New-ScheduledTaskAction -Execute "$workdir\run_grade3.bat"
$trigger3 = New-ScheduledTaskTrigger -Once -At '2026-05-05T10:00:00'
Register-ScheduledTask -TaskName 'QuizBot_grade3' -Action $action3 -Trigger $trigger3 -Force

Write-Host 'Done'
