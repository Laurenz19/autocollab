/* Terminal feedback shared by live runs and historical event replays. */
(function (root) {
  function describe(status, error = "") {
    const review = "Vérifiez les dernières actions et les fichiers avant de relancer pour éviter un doublon.";
    if (status === "termine") return null;
    if (status === "interrompu") return {
      title: "Exécution interrompue", message: "L'exécution a été interrompue par un redémarrage du serveur.", advice: review,
    };
    if (status === "arrete") return {
      title: "Exécution arrêtée", message: "L'arrêt demandé a été pris en compte.", advice: review,
    };
    const text = String(error || "");
    const rules = [
      [/Could not parse response|réponse au format invalide/i, "Réponse de l'IA invalide",
        "Le modèle n'a pas fourni une réponse exploitable pour poursuivre la tâche.",
        "Vérifiez les dernières actions avant de relancer. Si l'erreur se répète, demandez à un administrateur de vérifier le modèle d'IA."],
      [/nombre maximal d'étapes/i, "Limite d'étapes atteinte",
        "La tâche n'a pas pu être terminée dans le nombre d'étapes autorisé.",
        "Précisez la consigne ou découpez la tâche en plusieurs agents. Vérifiez le travail déjà effectué avant de relancer."],
      [/répétait la même action/i, "L'agent n'avançait plus",
        "L'exécution a été arrêtée après plusieurs actions identiques sans progression.",
        "Consultez la dernière capture et précisez dans la consigne une autre façon d'effectuer l'action."],
      [/Insufficient Balance|insufficient_quota|crédit insuffisant/i, "Crédit fournisseur insuffisant",
        "Le fournisseur d'IA ne permet plus de poursuivre les appels.",
        "Demandez à un administrateur de vérifier le crédit disponible chez le fournisseur d'IA."],
      [/clé d'IA|clé d'API|invalid_api_key|authenticationerror/i, "Configuration de l'IA à vérifier",
        "L'accès au modèle d'IA n'a pas pu être utilisé.",
        "Demandez à un administrateur de tester la connexion dans Administration › Intelligence artificielle."],
      [/navigateur.*démarrer|close all existing Chrome instances|ECONNREFUSED/i, "Navigateur indisponible",
        "Le navigateur de l'agent n'a pas pu démarrer.",
        "Fermez la session ouverte dans Mes connexions, puis réessayez. Si le problème persiste, contactez un administrateur."],
    ];
    for (const [pattern, title, message, advice] of rules) {
      if (pattern.test(text)) return { title, message, advice };
    }
    return { title: "La tâche n'a pas abouti", message: "Consultez le compte rendu et les étapes pour identifier ce qui reste à faire.", advice: review };
  }

  function stats(runs) {
    const finished = runs.filter(r => !["en_attente", "en_cours", "a_valider"].includes(r.status));
    const succeeded = finished.filter(r => r.status === "termine").length;
    const failed = finished.filter(r => r.status === "echec").length;
    return { succeeded, failed, other: finished.length - succeeded - failed,
      rate: finished.length ? Math.round(succeeded / finished.length * 100) : null };
  }

  const api = { describe, stats };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.RunFeedback = api;
})(typeof window !== "undefined" ? window : globalThis);
