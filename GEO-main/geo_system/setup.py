"""
GEO内容工程系统 - 安装配置
"""

from setuptools import setup, find_packages
import os

# 读取README
with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

# 读取requirements
with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = [line.strip() for line in fh if line.strip() and not line.startswith("#")]

setup(
    name="geo-system",
    version="1.0.0",
    author="GEO Team",
    author_email="support@geo-system.com",
    description="GEO内容工程系统 - AI搜索时代的内容优化解决方案",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/your-org/geo-system",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: Marketing/Internet",
        "Topic :: Internet :: WWW/HTTP :: Indexing/Search",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.8",
    install_requires=requirements,
    extras_require={
        "api": ["fastapi>=0.100.0", "uvicorn>=0.23.0"],
        "web": ["streamlit>=1.28.0"],
        "dev": ["pytest>=7.0.0", "black>=23.0.0", "flake8>=6.0.0"],
        "all": [
            "fastapi>=0.100.0",
            "uvicorn>=0.23.0",
            "streamlit>=1.28.0",
            "pytest>=7.0.0",
            "black>=23.0.0",
            "flake8>=6.0.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "geo=geo_system.cli.main:cli",
            "geo-server=geo_system.api.server:main",
            "geo-web=geo_system.web.app:create_web_app",
        ],
    },
    include_package_data=True,
    package_data={
        "geo_system": [
            "config/*.yaml",
            "templates/*.md",
            "examples/*.py",
            "examples/*.md",
        ],
    },
    project_urls={
        "Bug Reports": "https://github.com/your-org/geo-system/issues",
        "Source": "https://github.com/your-org/geo-system",
        "Documentation": "https://geo-system.readthedocs.io",
    },
)
