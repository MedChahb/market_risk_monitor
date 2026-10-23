# Note de restitution : risque du portefeuille au 22 octobre 2026

Mohammed Chahbaoui, 23 octobre 2026. Chiffres issus du calcul de la nuit du 22 au 23 octobre ; détail dans le rapport Power BI ([`docs/report.pdf`](report.pdf)).

**Le portefeuille.** 10 M€ : actions CAC 40, Euro Stoxx 50 et S&P 500 (2 M€ chacune), or (1 M€), obligation zéro-coupon euro AAA à 10 ans (2 M€) et dollars (1 M€). Les positions sont fixes ; le résultat (P&L) est calculé chaque jour en euros, change compris.

## Le risque aujourd'hui

Calculé sur la clôture du 21 octobre, pour la séance du 22 octobre (les cours de clôture de Paris du 22 n'étaient pas encore publiés au moment du calcul).

- **VaR 99 % à un jour : 96 900 €**, soit 0,97 % du portefeuille. Une perte plus forte est attendue un jour sur cent, deux à trois fois par an.
- **Expected Shortfall 97,5 % : 115 600 €**, la perte moyenne des 2,5 % de jours les plus mauvais.
- **C'est un niveau bas.** 86 % des VaR calculées depuis 2012 étaient plus élevées. Sur les 250 derniers jours, la VaR médiane est de 128 800 € et la plus haute de 277 100 € (23 mars 2026).
- **Un seul dépassement en un an** : le 3 mars 2026, une perte de 180 100 € pour une VaR de 100 000 €. Le portefeuille reste en zone verte du feu tricolore bâlois.

## La méthode retenue

La VaR est calculée par **simulation historique filtrée**. On prend les 500 derniers rendements du portefeuille, on ramène chacun à la volatilité de son jour, puis on les remet à l'échelle de la volatilité prévue pour le lendemain par un modèle GJR-GARCH. La VaR suit ainsi le niveau actuel des marchés tout en gardant la forme réelle des pertes passées.

Sur 3 824 jours depuis 2012, elle a été dépassée 38 fois pour 38,2 attendus. Ses dépassements ne s'enchaînent pas (tests de Kupiec et de Christoffersen passés), et elle n'a jamais été en zone rouge. C'est la seule des cinq méthodes testées qui passe tous les tests :

- la simulation historique simple réagit trop tard aux crises : 55 dépassements, groupés, avec des passages en zone rouge ;
- les VaR fondées sur la loi normale sont dépassées 54 à 74 fois, car la loi normale sous-estime les fortes pertes.

## Ce qu'il faut surveiller

1. **Un marché calme depuis le 22 juin 2026.** Le régime de marché estimé chaque soir donne une probabilité de calme supérieure à 99 % le 22 octobre. La volatilité du portefeuille sur 22 jours est de 5,9 % par an, contre 9,3 % en médiane sur 2008-2017 : la VaR basse en est la conséquence. Les chocs qui surviennent dans un marché calme sont ceux que les VaR fondées sur la loi normale sous-estiment (36 à 50 dépassements pour 21,9 attendus en régime calme). La VaR retenue reste proche de 1 % dans ce régime (28 pour 21,9).
2. **L'obligation ne protège plus les actions.** Sur les 250 derniers jours, la corrélation entre l'Euro Stoxx 50 et les variations du taux à 10 ans est de −0,47, contre +0,20 depuis 2008. Quand les actions baissent, les taux montent et l'obligation perd aussi : la diversification est plus faible que l'historique long ne le laisse penser.
3. **Des données plus calmes que la période d'apprentissage.** La variance du portefeuille sur les 250 dernières séances s'écarte nettement de celle de 2008-2017 (indice de stabilité PSI de 0,95 sur 22 jours ; au-delà de 0,25, l'écart est significatif), vers le bas. Les prévisions restent calibrées : le rendement divisé par la volatilité prévue n'a pas dérivé (PSI 0,06), et l'erreur du GJR-GARCH sur les 63 dernières séances reste sous celle du modèle de référence (QLIKE 0,25 contre 0,30 au 14 octobre).
4. **Le coût de sortie monte avec la volatilité.** Un ordre de 10 % du volume d'une séance coûte de 35 à 60 points de base selon l'action (22 octobre 2026). Pour TotalEnergies, ce coût a été multiplié par trois environ en mars 2020 : réduire les positions coûte plus cher précisément quand le marché se tend.

**Limites.** Le P&L est calculé à positions constantes, sans frais, portage ni opérations en cours de journée. Les données viennent de sources gratuites. La VaR à un jour ne mesure pas une crise de liquidité étalée sur plusieurs jours. Méthodes et limites détaillées : [fiches modèles](model_cards/README.md) et [runbook](runbook.md).
