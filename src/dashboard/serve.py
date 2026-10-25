"""Railway/container entry point; migrations are a separate pre-deploy command."""
import os
import uvicorn

if __name__ == '__main__':
    uvicorn.run('src.dashboard.app:app', host='0.0.0.0', port=int(os.getenv('PORT', '8000')),
                access_log=False, proxy_headers=False)
