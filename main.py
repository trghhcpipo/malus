import tkinter as tk

fenetre = tk.Tk()
fenetre.title("Mon premier programme")
fenetre.geometry("400x250")

texte = tk.Label(
    fenetre,
    text="Bonjour ! Mon programme fonctionne.",
    font=("Arial", 14)
)
texte.pack(pady=50)

bouton = tk.Button(
    fenetre,
    text="Fermer",
    command=fenetre.destroy
)
bouton.pack()

fenetre.mainloop()
