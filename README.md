I apologize for the confusion. You're right, and I see the issue now. Let's separate the Python code from the HTML elements completely. Here's the corrected version:
<p align="left">
  <img src="https://komarev.com/ghpvc/?username=Kamau-sam&color=00b3ff&style=flat-square&label=Profile+Views" alt="Profile Views" />
</p>

class Developer:
    def __init__(self, name, role, tech):
        self.name = name
        self.role = role
        self.tech = tech

Samuel_Kamau = Developer(
    name="Samuel Kamau",
    role="Software Developer",
    tech=["Javascript", "Python", "SQL"]
)

print(f"Name: {Samuel_Kamau.name}")
print(f"Role: {Samuel_Kamau.role}")
print(f"Technologies: {', '.join(Samuel_Kamau.tech)}")



<h3 align="center">GitHub Stats:</h3>
<p align="center">
  <img align="center" height="180em" src="https://github-readme-stats.vercel.app/api/top-langs/?username=Kamau-sam&langs_count=8&theme=neon" alt="Kamau-sam" />
  <img align="center" height="180em" src="https://github-readme-streak-stats.herokuapp.com/?user=Kamau-sam&theme=neon-dark" alt="Kamau-sam" />
</p>
