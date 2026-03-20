# arXiv Autopilot — demo recording
# Run with: vhs assets/demo.tape
# Install vhs: brew install vhs   (requires ffmpeg)

Output assets/demo.gif
Output assets/demo.mp4

Set Shell "zsh"
Set FontSize 14
Set Width 1200
Set Height 680
Set Theme "Dracula"
Set Padding 20
Set TypingSpeed 40ms
Set PlaybackSpeed 1.0

# Activate conda env so the arxiv command is available
Type "conda activate claudecode"
Enter
Sleep 1s

# Show the main help briefly
Type "arxiv --help"
Enter
Sleep 3s

# --- recommend ---
Sleep 500ms
Type "arxiv recommend \"3D gaussian splatting\" -n 4 --no-open"
Enter
Sleep 18s

# --- direction ---
Sleep 500ms
Type "arxiv direction \"flow matching\" --no-open"
Enter
Sleep 20s

# --- topic save ---
Sleep 500ms
Type "arxiv topic save \"Gaussian Opacity Fields for Real-time Rendering\""
Enter
Sleep 2s

Type "arxiv topic list"
Enter
Sleep 3s

Sleep 2s
