@echo off
setlocal
cd /d "%~dp0"
echo 注意：请先将 prompt/random_generator/api_profiles/example.yaml 复制为 deepseek2.yaml
echo      并填写你的 API Key，否则本脚本会使用占位密钥运行。
python run_generator.py --count 1450 --output output/prompts_deepseek-v4-flash.jsonl --api-config prompt/random_generator/api_profiles/example.yaml --workers 1
pause
