import React from "react";
import "../App.css";
import Post from "./post";
import Slider from "react-slick";
import { faHandPointRight } from "@fortawesome/free-regular-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";

const settings = {
  dots: false,
  infinite: false,
  speed: 500,
  slidesToShow: 1,
  slidesToScroll: 1,
};

const SlideShow = ({ posts, lang }) => (
  <div>
    <p className="tutorial">
      {lang === "pt_BR" ? "Arraste para o lado\t" : "Swipe right\t"}
      <FontAwesomeIcon icon={faHandPointRight} />
    </p>
    <Slider {...settings}>
      {posts.map((post) => <Post data={post} lang={lang} />)}
    </Slider>
  </div>
);

export default SlideShow;
