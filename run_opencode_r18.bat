@echo off
setlocal
cd /d "%~dp0"
echo OpenCode Go persistent generator (R18 mode, infinite loop + budget cooldown)
echo Press Ctrl+C to stop. Results are appended continuously.
echo Output: output/prompts_opencode_r18.jsonl (isolated from run_opencode.bat output)
echo Ledger: output/opencode_budget.jsonl (shared with run_opencode.bat, protected by multi-process lock)
python opencode_runner.py --count 27200 --output output/prompts_opencode_r18.jsonl --api-config prompt/random_generator/api_profiles/deepseek4.yaml --workers 64 --max-rating r18 --real-usage "5h:2,7d:22,30d:22"
pause
