import ko from "knockout";
import proj4 from "proj4";
import WidgetViewModel from "viewmodels/widget";
import bngpointWidgetTemplate from "templates/views/components/widgets/bngpoint.htm";

const NZTM_PROJ4 =
    "+proj=tmerc +lat_0=0 +lon_0=173 +k=0.9996 +x_0=1600000 +y_0=10000000 +ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +units=m +no_defs";
const WGS84_PROJ4 = "+proj=longlat +datum=WGS84 +no_defs";

// Approximate NZTM bounds (metres) covering NZ and its offshore islands
const NZTM_EASTING_RANGE = [1000000, 2200000];
const NZTM_NORTHING_RANGE = [4700000, 6300000];

/**
 * Widget for entering a central point as NZTM (stored as "easting,northing"),
 * accepting either NZTM or Long/Lat input.
 */
export default ko.components.register("bngpoint", {
    viewModel: function (params) {
        params.configKeys = ["placeholder"];
        WidgetViewModel.apply(this, [params]);

        this.coordOptions = ["NZTM", "Long/Lat"];
        this.coordFormat = ko.observable("NZTM");
        this.isSelected = ko.observable(false);
        this.errorMessage = ko.observable();
        this.messageVisible = ko.observable(false);
        this.bngVal = ko.observable(this.value() || undefined);

        this.parsePair = function (input) {
            const parts = input.replace(/\s/g, "").split(",");
            if (parts.length !== 2) {
                return null;
            }
            const first = Number(parts[0]);
            const second = Number(parts[1]);
            if (parts[0] === "" || parts[1] === "" || isNaN(first) || isNaN(second)) {
                return null;
            }
            return [first, second];
        };

        this.nztmTransform = function (input) {
            const pair = this.parsePair(input);
            if (!pair) {
                this.errorMessage(
                    "Entered value is not a valid NZTM coordinate. Please enter it as easting,northing and try again."
                );
                return "";
            }
            return this.formatNZTM(pair[0], pair[1]);
        };

        this.longLatTransform = function (input) {
            const pair = this.parsePair(input);
            if (!pair) {
                this.errorMessage(
                    "Entered value is not a valid Long/Lat coordinate. Please enter it as long,lat and try again."
                );
                return "";
            }
            try {
                const projected = proj4(WGS84_PROJ4, NZTM_PROJ4, pair);
                return this.formatNZTM(projected[0], projected[1]);
            } catch (err) {
                console.error(err);
                this.errorMessage(
                    "Issue reprojecting long/lat coordinates. Please check your value is in a correct format, and within New Zealand, and try again."
                );
                return "";
            }
        };

        this.formatNZTM = function (easting, northing) {
            const e = Math.round(easting);
            const n = Math.round(northing);
            if (
                e < NZTM_EASTING_RANGE[0] ||
                e > NZTM_EASTING_RANGE[1] ||
                n < NZTM_NORTHING_RANGE[0] ||
                n > NZTM_NORTHING_RANGE[1]
            ) {
                this.errorMessage(
                    "Coordinate is outside the NZTM boundary. Please check your input and try again."
                );
                return "";
            }
            return e + "," + n;
        };

        this.preview = ko.pureComputed(function () {
            const pre = this.bngVal();

            if (this.isSelected() === true) {
                this.errorMessage("");
                return;
            }
            if (!pre) {
                this.errorMessage("");
                return;
            }

            let result;
            if (this.coordFormat() === "NZTM") {
                result = this.nztmTransform(pre);
            } else if (this.coordFormat() === "Long/Lat") {
                result = this.longLatTransform(pre);
            } else {
                this.errorMessage(
                    "You have not selected a coordinate format. Please do so and enter the coordinate value again."
                );
                return;
            }

            if (result !== "") {
                this.value(result);
                this.errorMessage("");
                this.messageVisible(false);
                return result;
            }
            this.value("");
            if (!ko.unwrap(this.errorMessage)) {
                this.errorMessage(
                    "Input coordinate did not pass validation. Please check it is in one of the approved formats and try again."
                );
            }
            return "";
        }, this);
    },
    template: bngpointWidgetTemplate,
});
