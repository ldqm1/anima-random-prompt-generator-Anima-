@echo off
setlocal
cd /d "%~dp0"
python run_generator.py --count 1000 --output output/prompts_deepseek3.jsonl --api-config prompt/random_generator/api_profiles/deepseek3.yaml --workers 4
pause
