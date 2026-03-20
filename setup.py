"""Setup configuration for arxiv-autopilot."""

from setuptools import setup, find_packages

setup(
    name="arxiv-autopilot",
    version="0.1.0",
    description="AI-powered arXiv research analysis platform",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="seerier",
    author_email="",
    url="https://github.com/seerier/arxiv-agent",
    python_requires=">=3.9",
    packages=find_packages(exclude=["tests*"]),
    package_data={
        "arxiv_agent": [
            "reporter/templates/*.html",
            "web/templates/*.html",
        ],
    },
    install_requires=[
        "arxiv>=2.1.0",
        "anthropic>=0.40.0",
        "rich>=13.0.0",
        "click>=8.1.0",
        "jinja2>=3.1.0",
        "requests>=2.31.0",
        "pyyaml>=6.0",
        "python-dateutil>=2.8.0",
        "markdown>=3.5",
    ],
    extras_require={
        "semantic-search": [
            "sentence-transformers>=2.2.0",
        ],
        "web": [
            "fastapi>=0.110.0",
            "uvicorn>=0.29.0",
            "python-multipart>=0.0.9",
        ],
        "tui": [
            "textual>=0.50.0",
        ],
        "scheduler": [
            "apscheduler>=3.10.0",
        ],
        "all": [
            "sentence-transformers>=2.2.0",
            "fastapi>=0.110.0",
            "uvicorn>=0.29.0",
            "python-multipart>=0.0.9",
            "textual>=0.50.0",
            "apscheduler>=3.10.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "arxiv=arxiv_agent.cli:cli",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Science/Research",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
    ],
    include_package_data=True,
    zip_safe=False,
)
