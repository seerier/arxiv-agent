"""Setup configuration for the Arxiv Intelligence System package."""

from setuptools import setup, find_packages

with open("requirements.txt") as f:
    requirements = [
        line.strip()
        for line in f
        if line.strip() and not line.startswith("#")
    ]

setup(
    name="arxiv-intel",
    version="0.1.0",
    description="A comprehensive research intelligence platform for AI/CV/graphics papers",
    long_description=open("README.md").read() if __import__("os").path.exists("README.md") else "",
    long_description_content_type="text/markdown",
    author="Arxiv Intelligence System",
    python_requires=">=3.9",
    packages=find_packages(exclude=["tests*"]),
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "arxiv=arxiv_intel.cli:cli",
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
