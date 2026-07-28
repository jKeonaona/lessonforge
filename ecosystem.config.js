module.exports = {
  apps: [{
    name: "lessonforge",
    script: "app.py",
    interpreter: "/var/www/lessonforge/venv/bin/python",
    cwd: "/var/www/lessonforge",
    env: { PORT: "6100" }
  }]
};
