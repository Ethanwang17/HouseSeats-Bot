import asyncio
import subprocess
import sys
import logging

# Configure logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

async def run_bot(bot_file):
	try:
		process = await asyncio.create_subprocess_exec(
			sys.executable, bot_file,
			stdout=asyncio.subprocess.PIPE,
			stderr=asyncio.subprocess.PIPE
		)
		
		# Handle output streams
		async def read_stream(stream, prefix):
			while True:
				line = await stream.readline()
				if not line:
					break
				logger.info(f"{prefix}: {line.decode().strip()}")
		
		await asyncio.gather(
			read_stream(process.stdout, bot_file),
			read_stream(process.stderr, f"{bot_file} (error)")
		)
		
		await process.wait()
		
	except Exception as e:
		logger.error(f"Error running {bot_file}: {e}")
		raise

async def main():
	try:
		# Run both bots concurrently
		await asyncio.gather(
			run_bot('houseseats_bot.py'),
			run_bot('fillaseat_bot.py')
		)
	except Exception as e:
		logger.error(f"Error in main: {e}")
		sys.exit(1)

if __name__ == "__main__":
	asyncio.run(main())