$workdir = 'C:\Users\kawak\line-quiz-bot'

$action1 = New-ScheduledTaskAction -Execute "$workdir\run_social_day1.bat"
$trigger1 = New-ScheduledTaskTrigger -Once -At '2026-05-08T14:00:00'
Register-ScheduledTask -TaskName 'SocialBot_day1' -Action $action1 -Trigger $trigger1 -Force

$action2 = New-ScheduledTaskAction -Execute "$workdir\run_social_day2.bat"
$trigger2 = New-ScheduledTaskTrigger -Once -At '2026-05-09T14:00:00'
Register-ScheduledTask -TaskName 'SocialBot_day2' -Action $action2 -Trigger $trigger2 -Force

$action3 = New-ScheduledTaskAction -Execute "$workdir\run_social_day3.bat"
$trigger3 = New-ScheduledTaskTrigger -Once -At '2026-05-10T14:00:00'
Register-ScheduledTask -TaskName 'SocialBot_day3' -Action $action3 -Trigger $trigger3 -Force

$action4 = New-ScheduledTaskAction -Execute "$workdir\run_social_day4.bat"
$trigger4 = New-ScheduledTaskTrigger -Once -At '2026-05-11T14:00:00'
Register-ScheduledTask -TaskName 'SocialBot_day4' -Action $action4 -Trigger $trigger4 -Force

$action5 = New-ScheduledTaskAction -Execute "$workdir\run_social_day5.bat"
$trigger5 = New-ScheduledTaskTrigger -Once -At '2026-05-12T14:00:00'
Register-ScheduledTask -TaskName 'SocialBot_day5' -Action $action5 -Trigger $trigger5 -Force

$action6 = New-ScheduledTaskAction -Execute "$workdir\run_social_day6.bat"
$trigger6 = New-ScheduledTaskTrigger -Once -At '2026-05-13T14:00:00'
Register-ScheduledTask -TaskName 'SocialBot_day6' -Action $action6 -Trigger $trigger6 -Force

Write-Host 'Done'
