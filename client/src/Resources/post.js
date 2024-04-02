import React from "react";
import "../App.css";

import Card from "react-bootstrap/Card";
import Button from "react-bootstrap/Button";

const Post = ({ data, lang }) => (
  <Card>
    <h2 className="tit">{lang === "pt_BR" ? data.title : data.title_en}</h2>
    <span className="data-bullet">{data.date}</span>
    <ul>
      {lang === "pt_BR"
        ? data.summary.map((item, index) => <li key={index}>{item}</li>)
        : data.summary_en.map((item, index) => <li key={index}>{item}</li>)}
    </ul>
    <Button href={data.link} className="button-tit">
      {lang === "pt_BR" ? "Quero saber mais" : "Read in Portuguese"}
    </Button>
  </Card>
);

export default Post;
