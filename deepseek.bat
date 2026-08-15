@echo off
cd /d "%~dp0"
python run_generator.py --count 1000 --output output/prompts_prompt_v5.jsonl --api-config prompt/random_generator/api_profiles/example.yaml --workers 8
pause
