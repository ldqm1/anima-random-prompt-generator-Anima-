@echo off
setlocal
cd /d "%~dp0"
echo OpenCode Go persistent generator (infinite loop + budget cooldown)
echo Press Ctrl+C to stop. Results are appended continuously.
python opencode_runner.py --count 0 --output output/prompts_opencode.jsonl --api-config prompt/random_generator/api_profiles/deepseek4.yaml --workers 8 --real-usage "5h:2,7d:50,30d:36" --balance 0.25
pause
