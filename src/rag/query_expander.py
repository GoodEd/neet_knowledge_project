_MAX_WORDS_FOR_EXPANSION = 5

NEET_SYNONYMS: dict[str, list[str]] = {
    "young modulus": [
        "young's modulus",
        "modulus of elasticity",
        "elastic stiffness",
        "stress strain ratio",
    ],
    "young's modulus": [
        "young modulus",
        "modulus of elasticity",
        "elastic constant",
    ],
    "wien": ["wien displacement law", "blackbody radiation peak"],
    "wien law": ["wien displacement law", "blackbody displacement"],
    "dark fringes": ["destructive interference fringes", "minima fringes"],
    "fringes": ["interference bands", "bright and dark bands"],
    "fringe width": ["interference pattern spacing", "beta in yds"],
    "osmosis": ["water potential movement", "semi permeable membrane flow"],
    "mitosis": ["equational division", "somatic cell division"],
    "meiosis": ["reduction division", "gamete formation division"],
    "newton's laws": ["laws of motion", "newton laws of motion"],
    "ohm's law": ["voltage current resistance relation", "v equals ir"],
    "elasticity": ["elastic behavior", "stress strain relation"],
    "viscosity": ["fluid internal friction", "coefficient of viscosity"],
    "thermodynamics": ["heat and work", "laws of thermodynamics"],
    "wave optics": ["interference and diffraction", "physical optics"],
    "electromagnetic": ["em waves", "electromagnetic radiation"],
    "photoelectric": ["photoelectric effect", "einstein photoelectric equation"],
    "radioactivity": ["nuclear decay", "radioactive disintegration"],
    "simple harmonic": ["simple harmonic motion", "shm oscillation"],
    "semiconductor": ["p n junction", "intrinsic and extrinsic semiconductor"],
    "capacitor": ["capacitance", "electric charge storage"],
    "magnetic field": ["magnetic flux density", "field around current"],
    "acid base": ["acidic basic reactions", "ph and neutralization"],
    "genetics": ["inheritance", "mendelian genetics"],
    "ecology": ["ecosystem interactions", "environmental biology"],
    "human physiology": ["human body systems", "physiological processes"],
    "plant physiology": ["plant functions", "transport in plants"],
    "biomolecules": ["proteins carbohydrates lipids", "biological macromolecules"],
    "cell biology": ["cell structure and function", "cell organelles"],
    "evolution": ["natural selection", "origin of species"],
    "reproduction": ["sexual and asexual reproduction", "reproductive biology"],
    "rotational motion": ["angular motion", "torque and moment of inertia"],
    "gravitation": ["universal law of gravitation", "gravitational force"],
    "surface tension": ["liquid surface energy", "capillary rise"],
    "organic chemistry": ["carbon compounds", "reaction mechanisms"],
    "chemical bonding": [
        "ionic covalent metallic bonding",
        "bond order and hybridization",
    ],
    "lens": ["convex concave lens", "lens formula"],
    "mirror": ["concave convex mirror", "mirror formula"],
    "kirchhoff": ["kirchhoff laws", "junction and loop rules"],
}


def expand_query(query: str) -> list[str]:
    words = query.split()
    if len(words) > _MAX_WORDS_FOR_EXPANSION:
        return [query]

    normalized = query.strip().lower()
    if not normalized:
        return [query]

    variants: list[str] = [query]
    seen = {query.lower()}

    exact_matches = NEET_SYNONYMS.get(normalized, [])
    for candidate in exact_matches:
        lowered = candidate.lower()
        if lowered not in seen:
            variants.append(candidate)
            seen.add(lowered)
        if len(variants) >= 5:
            return variants

    for key, synonyms in NEET_SYNONYMS.items():
        if key == normalized:
            continue
        if key in normalized or normalized in key:
            for candidate in synonyms:
                lowered = candidate.lower()
                if lowered in seen:
                    continue
                variants.append(candidate)
                seen.add(lowered)
                if len(variants) >= 5:
                    return variants

    return variants
