ThisBuild / scalaVersion := "2.13.10"
ThisBuild / organization := "comparison"
ThisBuild / version := "0.1.0"
ThisBuild / scalacOptions ++= Seq("-deprecation", "-unchecked", "-Ymacro-annotations")

val chipyardSource = file(sys.env("CHIPYARD_SOURCE")).getCanonicalFile
val gemminiSource = file(sys.env("GEMMINI_SOURCE")).getCanonicalFile
def cy(path: String): String = (chipyardSource / path).getAbsolutePath
def gm(path: String): String = (gemminiSource / path).getAbsolutePath

val chiselVersion = "3.6.1"
val common = Seq(
  libraryDependencies ++= Seq(
    "edu.berkeley.cs" %% "chisel3" % chiselVersion,
    "com.lihaoyi" %% "sourcecode" % "0.3.1",
    "org.apache.commons" % "commons-lang3" % "3.12.0",
    "org.apache.commons" % "commons-text" % "1.9"),
  addCompilerPlugin("edu.berkeley.cs" % "chisel3-plugin" % chiselVersion cross CrossVersion.full))

def official(id: String, source: String, resources: Option[String] = None) =
  Project(id, file("projects/" + id)).settings(common).settings(
    Compile / unmanagedSourceDirectories := Seq(file(source)),
    Compile / unmanagedResourceDirectories := resources.map(file).toSeq)

lazy val targetutils = official("targetutils", cy("sims/firesim/sim/midas/targetutils/src/main/scala"))
lazy val hardfloat = official("hardfloat", cy("generators/hardfloat/hardfloat/src/main/scala")).dependsOn(targetutils)
lazy val cde = official("cde", cy("tools/cde/cde/src/chipsalliance/rocketchip"))
lazy val diplomacy = official("diplomacy", cy("generators/diplomacy/diplomacy/src/diplomacy")).dependsOn(cde)
lazy val macros = official("rocketmacros", cy("generators/rocket-chip/macros/src/main/scala")).settings(
  libraryDependencies += "org.scala-lang" % "scala-reflect" % scalaVersion.value)
lazy val rocketchip = official("rocketchip", cy("generators/rocket-chip/src/main/scala"),
  Some(cy("generators/rocket-chip/src/main/resources"))).dependsOn(hardfloat, cde, macros, diplomacy).settings(
  libraryDependencies ++= Seq(
    "com.lihaoyi" %% "mainargs" % "0.5.0",
    "org.scala-lang" % "scala-reflect" % scalaVersion.value,
    "org.json4s" %% "json4s-jackson" % "4.0.5",
    "org.scala-graph" %% "graph-core" % "1.13.5"))
lazy val gemmini = official("gemmini", gm("src/main/scala"),
  Some(gm("src/main/resources"))).dependsOn(rocketchip)
lazy val compare = (project in file(".")).settings(common).dependsOn(gemmini)
